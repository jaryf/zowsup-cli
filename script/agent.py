#!/usr/bin/env python3
"""script/agent.py
──────────────────
Zowsup Agent Process

Connects to the backend's /agent WebSocket namespace, receives commands,
manages local bot subprocesses, and streams log events back.

Usage
─────
    python script/agent.py

Environment variables
─────────────────────
AGENT_ID            Unique identifier for this agent  (default: hostname)
AGENT_KEY_ID        HMAC key ID  (default: "default")
AGENT_KEY_SECRET    Shared HMAC secret — REQUIRED
BACKEND_URL         Backend WebSocket base URL  (default: http://localhost:5000)
AGENT_PHONES        Comma-separated list of phones to manage
                    (if unset, auto-discovers from data/bot_status_*.json)

How it works
────────────
1. Connects to BACKEND_URL on the /agent namespace with a signed auth token.
2. Emits `agent_ready` with the phone list it manages.
3. Listens for `command` events:  start_bot / stop_bot / get_status / list_phones
4. Sends `command_ack` after handling each command.
5. Tails logs/<phone>.log and emits `agent_event` {type: bot_log, …}.
6. Emits `agent_event` {type: heartbeat} every 30 s with all bot statuses.
7. Reconnects automatically with a fresh signed token on disconnect.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# ── Project root on path ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(name)-24s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import socketio as sio_lib
except ImportError:
    logger.error(
        "python-socketio[client] is required.\n"
        "  pip install 'python-socketio[client]' websocket-client"
    )
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
AGENT_ID = os.environ.get("AGENT_ID", socket.gethostname())
KEY_SECRET = os.environ.get("AGENT_KEY_SECRET", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:5000")

if not KEY_SECRET:
    logger.error("AGENT_KEY_SECRET is not set. Refusing to start.")
    sys.exit(1)

# ── Bot subprocess registry ───────────────────────────────────────────────────
_bot_procs: dict[str, subprocess.Popen] = {}   # phone -> Popen
_bot_procs_lock = threading.Lock()

# ── Log tail threads ──────────────────────────────────────────────────────────
_log_tail_threads: dict[str, threading.Thread] = {}
_log_tail_stop: dict[str, threading.Event] = {}

_LOG_LINE_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2}))\]\s+(\S+)\s+"
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(?:\[\S+:\d+\]\s+)?(.+)$"
)


# ── SocketIO client ───────────────────────────────────────────────────────────
# reconnection=False: we control the loop to regenerate the signed auth token.
sio = sio_lib.Client(reconnection=False, logger=False, engineio_logger=False)

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _make_auth() -> dict:
    """Build a fresh HMAC-signed connect auth payload."""
    signed_at = int(time.time())
    sig = hmac.new(
        bytes.fromhex(KEY_SECRET) if len(KEY_SECRET) == 64 else KEY_SECRET.encode(),
        f"{AGENT_ID}:{signed_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "agent_id": AGENT_ID,
        "signed_at": signed_at,
        "sig": sig,
    }


# ── Phone discovery ───────────────────────────────────────────────────────────

def _discover_phones() -> list[str]:
    data_dir = ROOT / "data"
    if not data_dir.exists():
        return []
    phones = []
    for f in data_dir.glob("bot_status_*.json"):
        phone = f.stem[len("bot_status_"):]
        if phone.isdigit():
            phones.append(phone)
    return phones


def _phone_list() -> list[str]:
    env = os.environ.get("AGENT_PHONES", "").strip()
    if env:
        return [p.strip().lstrip("+") for p in env.split(",") if p.strip()]
    return _discover_phones()


# ── Bot management ────────────────────────────────────────────────────────────

def _start_bot(phone: str) -> dict:
    from app.dashboard.utils.bot_status import read_status
    status = read_status(phone=phone)
    if status.get("running") and status.get("pid"):
        try:
            os.kill(status["pid"], 0)   # check alive
            return {"ok": True, "already_running": True, "pid": status["pid"], "phone": phone}
        except (ProcessLookupError, PermissionError):
            pass

    script = ROOT / "script" / "main.py"
    if not script.exists():
        return {"ok": False, "error": "script/main.py not found"}

    with _bot_procs_lock:
        prev = _bot_procs.get(phone)
        if prev and prev.poll() is None:
            try:
                prev.terminate()
            except OSError:
                pass
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script), phone],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(ROOT),
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                # Tell the bot to forward messages to the backend server
                # instead of trying to write to a local dashboard.db.
                "AGENT_MODE": "1",
                "AGENT_ID": AGENT_ID,
                "AGENT_KEY_SECRET": KEY_SECRET,
                "AGENT_BACKEND_URL": BACKEND_URL,
            },
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    with _bot_procs_lock:
        _bot_procs[phone] = proc

    # Drain stdout so the pipe never blocks
    threading.Thread(
        target=_drain_proc_stdout,
        args=(proc,),
        daemon=True,
        name=f"drain-{phone}",
    ).start()

    logger.info("Bot started phone=%s PID=%s", phone, proc.pid)
    _ensure_log_tail(phone)
    return {"ok": True, "pid": proc.pid, "phone": phone}


def _stop_bot(phone: str) -> dict:
    from app.dashboard.utils.bot_status import read_status, clear_status

    stopped_pid: Optional[int] = None
    with _bot_procs_lock:
        proc = _bot_procs.pop(phone, None)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            stopped_pid = proc.pid
        except OSError:
            pass

    if stopped_pid is None:
        status = read_status(phone=phone)
        pid = status.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped_pid = pid
            except (ProcessLookupError, PermissionError):
                pass

    if stopped_pid:
        clear_status(phone=phone)
        logger.info("Bot stopped phone=%s PID=%s", phone, stopped_pid)
        return {"ok": True, "pid": stopped_pid, "phone": phone}
    return {"ok": False, "error": "bot was not running", "phone": phone}


def _bot_status(phone: str) -> dict:
    from app.dashboard.utils.bot_status import read_status
    status = read_status(phone=phone)
    running = status.get("running", False)
    pid = status.get("pid")
    if running and pid:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            running = False

    # If the status file hasn't been written yet (bot just launched),
    # fall back to the in-memory process registry.
    if not running:
        with _bot_procs_lock:
            proc = _bot_procs.get(phone)
        if proc and proc.poll() is None:
            running = True
            pid = proc.pid

    uptime = None
    if running and status.get("started_at"):
        uptime = int(time.time() - status["started_at"])
    return {
        "running": running,
        "jid": status.get("jid"),
        "pid": pid if running else None,
        "phone": phone,
        "uptime_seconds": uptime,
    }


def _all_statuses() -> list[dict]:
    return [_bot_status(p) for p in _phone_list()]


def _emit_bot_status(phone: str) -> None:
    """Emit a bot_status event for *phone* to the backend (fire-and-forget)."""
    try:
        status = _bot_status(phone)
        sio.emit(
            "agent_event",
            {"type": "bot_status", "payload": status},
            namespace="/agent",
        )
    except Exception as exc:
        logger.debug("_emit_bot_status failed: %s", exc)


def _enqueue_send_task(payload: dict) -> dict:
    """Write a send task to the local send_queue.json for the bot to pick up."""
    try:
        from app.dashboard.utils.send_queue import enqueue_send_task
        task_id = enqueue_send_task(
            to_jid=payload.get("to_jid", ""),
            message_type=payload.get("message_type", "text"),
            content=payload.get("content", ""),
            bot_jid=payload.get("bot_jid"),
            media_url=payload.get("media_url"),
            caption=payload.get("caption"),
        )
        logger.info("Send task enqueued locally: %s → %s", task_id, payload.get("to_jid"))
        return {"ok": True, "task_id": task_id}
    except Exception as exc:
        logger.error("Failed to enqueue send task: %s", exc)
        return {"ok": False, "error": str(exc)}


def _drain_proc_stdout(proc: subprocess.Popen) -> None:
    try:
        for _ in proc.stdout:  # type: ignore[union-attr]
            pass
    except Exception:
        pass


# ── Log tailing ───────────────────────────────────────────────────────────────

def _parse_log_line(line: str) -> Optional[dict]:
    m = _LOG_LINE_RE.match(line.rstrip())
    if not m:
        return None
    return {
        "ts": m.group(2),
        "level": m.group(4),
        "logger": m.group(3),
        "message": m.group(5),
    }


def _tail_log_loop(phone: str, stop_ev: threading.Event) -> None:
    log_path = ROOT / "logs" / f"{phone}.log"
    fh = None
    last_inode = None
    last_size = 0
    absent_count = 0

    while not stop_ev.is_set():
        time.sleep(0.5)
        try:
            if not log_path.exists():
                if fh:
                    fh.close()
                    fh = None
                last_inode = None
                last_size = 0
                absent_count += 1
                if absent_count > 60:
                    break
                continue
            absent_count = 0
            st = log_path.stat()
            cur_inode = st.st_ino
            cur_size = st.st_size
            if fh is None or cur_inode != last_inode or cur_size < last_size:
                if fh:
                    fh.close()
                fh = open(log_path, "r", encoding="utf-8", errors="replace")
                fh.seek(0, 2)   # seek to end — only new lines
                last_inode = cur_inode
                last_size = cur_size
                continue
            for raw in fh:
                entry = _parse_log_line(raw)
                if entry:
                    try:
                        sio.emit(
                            "agent_event",
                            {"type": "bot_log", "payload": {**entry, "bot_id": phone}},
                            namespace="/agent",
                        )
                    except Exception:
                        pass
            last_size = log_path.stat().st_size
        except Exception:
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
            fh = None
    if fh:
        try:
            fh.close()
        except Exception:
            pass


def _ensure_log_tail(phone: str) -> None:
    existing = _log_tail_threads.get(phone)
    if existing and existing.is_alive():
        return
    stop_ev = threading.Event()
    _log_tail_stop[phone] = stop_ev
    t = threading.Thread(
        target=_tail_log_loop,
        args=(phone, stop_ev),
        daemon=True,
        name=f"tail-{phone}",
    )
    _log_tail_threads[phone] = t
    t.start()
    logger.debug("Log tail started for phone=%s", phone)


# ── SocketIO event handlers ───────────────────────────────────────────────────

@sio.event(namespace="/agent")
def connect():
    logger.info("Connected to backend %s as agent=%s", BACKEND_URL, AGENT_ID)
    phones = _phone_list()
    sio.emit("agent_ready", {"phones": phones, "agent_id": AGENT_ID}, namespace="/agent")
    for phone in phones:
        _ensure_log_tail(phone)
        status = _bot_status(phone)
        sio.emit("agent_event", {"type": "bot_status", "payload": status}, namespace="/agent")


@sio.event(namespace="/agent")
def connect_error(data):
    logger.error("Connection error: %s", data)


@sio.event(namespace="/agent")
def disconnect():
    logger.warning("Disconnected from backend")


@sio.event(namespace="/agent")
def command(data):
    """Handle inbound command from backend."""
    if not isinstance(data, dict):
        return
    cmd_id = str(data.get("cmd_id", ""))
    cmd_type = str(data.get("type", ""))
    payload = data.get("payload") or {}
    phone = str(payload.get("phone", "")).strip().lstrip("+")

    logger.info("cmd %s type=%s phone=%s", cmd_id, cmd_type, phone)
    result: dict = {}
    try:
        if cmd_type == "start_bot":
            if not phone:
                result = {"ok": False, "error": "phone required"}
            else:
                result = _start_bot(phone)
                # Emit status immediately (process alive → running=True via _bot_procs check)
                _emit_bot_status(phone)
                # Schedule a re-emit after the bot has had time to connect and write
                # its status file (so the JID gets propagated too)
                threading.Timer(8.0, _emit_bot_status, args=(phone,)).start()
                threading.Timer(20.0, _emit_bot_status, args=(phone,)).start()
        elif cmd_type == "stop_bot":
            if not phone:
                result = {"ok": False, "error": "phone required"}
            else:
                result = _stop_bot(phone)
                # Emit updated status immediately so backend doesn't wait for heartbeat
                _emit_bot_status(phone)
        elif cmd_type == "get_status":
            if phone:
                result = _bot_status(phone)
            else:
                result = {"bots": _all_statuses()}
        elif cmd_type == "list_phones":
            result = {"phones": _phone_list()}
        elif cmd_type == "send_message":
            result = _enqueue_send_task(payload)
        else:
            result = {"ok": False, "error": f"unknown command: {cmd_type}"}
    except Exception as exc:
        logger.exception("Command %s failed", cmd_type)
        result = {"ok": False, "error": str(exc)}

    if cmd_id:
        sio.emit("command_ack", {"cmd_id": cmd_id, "type": cmd_type, **result}, namespace="/agent")


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def _heartbeat_loop() -> None:
    while True:
        time.sleep(30)
        if not sio.connected:
            continue
        try:
            sio.emit(
                "agent_event",
                {
                    "type": "heartbeat",
                    "payload": {
                        "agent_id": AGENT_ID,
                        "bots": _all_statuses(),
                        "ts": int(time.time()),
                    },
                },
                namespace="/agent",
            )
        except Exception as exc:
            logger.debug("Heartbeat emit failed: %s", exc)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat").start()

    _stop = threading.Event()

    def _on_stop(*_):
        if _stop.is_set():
            return
        logger.info("Stop signal received — shutting down")
        _stop.set()
        try:
            sio.disconnect()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)   # handle Ctrl+C

    logger.info("Agent %s starting → %s", AGENT_ID, BACKEND_URL)

    while not _stop.is_set():
        auth = _make_auth()
        try:
            sio.connect(
                BACKEND_URL,
                auth=auth,
                namespaces=["/agent"],
                transports=["websocket"],
                wait_timeout=10,
            )
            sio.wait()
        except sio_lib.exceptions.ConnectionError as exc:
            logger.warning("Connection failed: %s — retry in 5 s", exc)
        except Exception as exc:
            logger.error("Unexpected error: %s — retry in 5 s", exc)

        if _stop.is_set():
            break
        if sio.connected:
            try:
                sio.disconnect()
            except Exception:
                pass
        time.sleep(5)

    logger.info("Agent stopped")


if __name__ == "__main__":
    main()
