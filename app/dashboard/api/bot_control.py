"""
app/dashboard/api/bot_control.py
─────────────────────────────────
Phase 5: Bot login management API.

Endpoints
---------
GET  /api/bot/status          — Current bot running state (reads data/bot_status.json)
POST /api/bot/login-scan      — Launch regwithscan.py subprocess; returns {pid}
GET  /api/bot/qr-stream       — SSE stream that pushes QR-code lines from subprocess stdout
POST /api/bot/login-linkcode  — Launch regwithlinkcode.py; return 8-char link code
POST /api/bot/logout          — Send SIGTERM to running bot via PID in status file

Design constraints
------------------
- Everything is synchronous WSGI; no asyncio, no eventlet/gevent.
- Bot communication is file-based (data/bot_status.json, data/bot.pid).
- Subprocess stdout is read with Popen(stdout=PIPE) — never blocking run().
- QR stream ends automatically when subprocess exits or bot logs in.
- All mutating endpoints (POST) are rate-limited via the shared limiter.
"""

import json
import logging
import hashlib
import hmac
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from flask import Blueprint, Response, current_app, request, stream_with_context

from app.dashboard.api.auth import check_bearer
from app.dashboard.api.rate_limit import limiter
from app.dashboard.utils.bot_status import read_status, read_all_statuses, _pid_alive

logger = logging.getLogger(__name__)

bot_bp = Blueprint("bot", __name__)

# ---------------------------------------------------------------------------
# BOT_DRIVER_MODE
# ---------------------------------------------------------------------------
# Controls how start/stop/status commands are dispatched.
#
#   "agent"  — always route to a connected agent; return 503 if no agent found
#   "local"  — always run as a local subprocess; never try agent
#   ""       — (default) try agent first, fall back to local if no agent manages
#              the phone  (backwards-compatible behaviour)
#
_BOT_DRIVER_MODE: str = os.environ.get("BOT_DRIVER_MODE", "").strip().lower()


# ---------------------------------------------------------------------------
# Agent routing helper
# ---------------------------------------------------------------------------

def _try_agent_command(phone: str, cmd_type: str, payload: dict) -> "dict | None":
    """
    Dispatch *cmd_type* to the agent that manages *phone*.

    Behaviour depends on BOT_DRIVER_MODE:
    - "local"  → always return None (never use agent)
    - "agent"  → always attempt; raises RuntimeError when no agent is found
    - ""       → attempt if an agent manages the phone, else return None
    """
    if _BOT_DRIVER_MODE == "local":
        return None
    try:
        from app.dashboard.api.agent_gateway import get_agent_for_phone, dispatch_command
        agent_id = get_agent_for_phone(phone)
        if agent_id is None:
            if _BOT_DRIVER_MODE == "agent":
                raise RuntimeError(f"BOT_DRIVER_MODE=agent but no agent manages phone={phone}")
            return None
        result = dispatch_command(agent_id, cmd_type, payload)
        return result
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Agent command %s failed for %s: %s", cmd_type, phone, exc)
        return None

# Path to the running QR subprocess, held in memory.
# Single-instance assumption: only one scan session at a time.
_qr_proc: "subprocess.Popen | None" = None

_PID_FILE = Path("data") / "bot.pid"
_BOT_STARTUP_TIMEOUT = 30  # seconds to wait for link-code to appear
_BOT_CONNECT_TIMEOUT = 60  # seconds to wait for main.py to reach running state

# Dict of running main.py processes keyed by phone string.
# Replaces the old single _start_proc variable.
_start_procs: "dict[str, subprocess.Popen]" = {}


# ---------------------------------------------------------------------------
# Auth guard applied to every route in this blueprint
# ---------------------------------------------------------------------------

@bot_bp.before_request
def _bot_auth():
    result = check_bearer()
    if result is not None:
        return result


# ---------------------------------------------------------------------------
# B.1  GET /api/bot/status
# ---------------------------------------------------------------------------

@bot_bp.get("/agents")
def get_agents():
    """
    Return all *defined* agents merged with their current runtime state.
    An agent is online when it has an active WebSocket connection.
    """
    from app.dashboard.api.agent_gateway import get_all_agents
    from app.dashboard.utils.agents_store import list_agents

    defined = {a["agent_id"]: a for a in list_agents()}
    online = {a["agent_id"]: a for a in get_all_agents()}

    merged = []
    # defined agents first (ordered by creation time)
    for agent_id, defn in sorted(defined.items(), key=lambda x: x[1].get("created_at") or 0):
        rt = online.get(agent_id)
        merged.append({
            "agent_id": agent_id,
            "note": defn.get("note", ""),
            "created_at": defn.get("created_at"),
            "online": rt is not None,
            "phones": rt["phones"] if rt else [],
            "connected_at": rt.get("connected_at") if rt else None,
            "uptime_seconds": rt.get("uptime_seconds") if rt else None,
        })
    # online but not yet defined (edge case — env-var auth)
    for agent_id, rt in online.items():
        if agent_id not in defined:
            merged.append({
                "agent_id": agent_id,
                "note": "",
                "created_at": None,
                "online": True,
                "phones": rt["phones"],
                "connected_at": rt.get("connected_at"),
                "uptime_seconds": rt.get("uptime_seconds"),
            })
    return {"agents": merged}


# ---------------------------------------------------------------------------
# Agent definition CRUD  POST/DELETE /api/bot/agents
# ---------------------------------------------------------------------------

@bot_bp.post("/agents")
@limiter.limit("20 per minute")
def post_agent():
    """
    Define a new agent on the server.
    Body: {"agent_id": "server-hk-01", "note": "optional label"}
    Response (201): {"agent_id": ..., "secret": "<hex — shown once>", "launch_cmd": "..."}
    """
    from app.dashboard.utils.agents_store import add_agent
    body = request.get_json(silent=True) or {}
    agent_id = str(body.get("agent_id", "")).strip()
    note = str(body.get("note", "")).strip()
    if not agent_id:
        return {"error": "agent_id required"}, 400
    if not agent_id.replace("-", "").replace("_", "").isalnum():
        return {"error": "agent_id must be alphanumeric (hyphens/underscores allowed)"}, 400
    try:
        secret_hex = add_agent(agent_id, note)
    except ValueError as exc:
        return {"error": str(exc)}, 409
    backend_url = request.host_url.rstrip("/")
    launch_cmd = (
        f"AGENT_ID={agent_id} "
        f"AGENT_KEY_SECRET={secret_hex} "
        f"BACKEND_URL={backend_url} "
        f"python script/agent.py"
    )
    return {
        "agent_id": agent_id,
        "note": note,
        "secret": secret_hex,
        "launch_cmd": launch_cmd,
    }, 201


@bot_bp.delete("/agents/<agent_id>")
@limiter.limit("20 per minute")
def delete_agent_def(agent_id: str):
    """
    Delete an agent definition.
    The agent will be rejected on its next reconnect attempt.
    """
    from app.dashboard.utils.agents_store import delete_agent
    deleted = delete_agent(agent_id)
    if not deleted:
        return {"error": f"Agent '{agent_id}' not defined"}, 404
    return {"ok": True, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Agent ingest — B.1b  POST /api/bot/ingest
# ---------------------------------------------------------------------------

_INGEST_AUTH_WINDOW = 120  # seconds


def _verify_ingest_auth(header_value: str) -> bool:
    """
    Verify the X-Agent-Auth header sent by agent-mode bot subprocesses.
    Format: <agent_id>:<signed_at>:<hex_sig>
    """
    try:
        agent_id, signed_at_str, sig = header_value.split(":", 2)
        signed_at = int(signed_at_str)
    except (ValueError, AttributeError):
        return False
    if abs(time.time() - signed_at) > _INGEST_AUTH_WINDOW:
        return False
    try:
        from app.dashboard.utils.agents_store import get_agent_secret
        secret = get_agent_secret(agent_id)
        if secret is None:
            return False
        expected = hmac.new(secret, f"{agent_id}:{signed_at}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


@bot_bp.post("/ingest")
def ingest_message():
    """
    Receive a chat message forwarded from an agent-mode bot subprocess and
    persist it to dashboard.db.  Authenticated via X-Agent-Auth header
    (same HMAC scheme as the WebSocket /agent namespace).

    Body JSON fields:
      bot_jid, user_jid, direction, content, message_type,
      participant, notify, media_path, source, timestamp (optional)
    """
    auth_header = request.headers.get("X-Agent-Auth", "")
    if not _verify_ingest_auth(auth_header):
        return {"error": "unauthorized"}, 401

    body = request.get_json(silent=True) or {}
    bot_jid = body.get("bot_jid") or ""
    user_jid = body.get("user_jid") or ""
    direction = body.get("direction") or "in"
    content = body.get("content") or ""
    message_type = body.get("message_type") or "text"
    participant = body.get("participant")
    notify = body.get("notify")
    media_path = body.get("media_path")
    source = body.get("source")
    timestamp = int(body.get("timestamp") or time.time())

    if not user_jid or not content:
        return {"error": "user_jid and content are required"}, 400

    try:
        from app.dashboard.config import CONFIG  # noqa: PLC0415
        db_path = CONFIG.get("DASHBOARD_DB_PATH")
        if not db_path:
            return {"error": "dashboard db not configured"}, 503
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO chat_messages "
                "(user_jid, direction, content, message_type, timestamp, bot_jid, "
                " participant, notify, media_path, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_jid, direction, content, message_type, timestamp, bot_jid,
                 participant, notify, media_path, source),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("ingest_message db write failed: %s", exc)
        return {"error": "db write failed"}, 500

    # Notify connected dashboard clients in real-time
    try:
        sio = current_app.extensions.get("socketio")
        if sio:
            sio.emit("new_message", {
                "bot_jid": bot_jid,
                "user_jid": user_jid,
                "direction": direction,
                "content": content,
                "message_type": message_type,
                "timestamp": timestamp,
            })
    except Exception as exc:
        logger.debug("ingest socket emit failed: %s", exc)

    return {"ok": True}, 201


@bot_bp.get("/status")
def get_bot_status():
    """Return running state of a single bot (query ?phone=X) or legacy single-bot."""
    phone = request.args.get("phone", "").strip().lstrip("+")
    # Try agent first when phone is specified
    if phone:
        agent_result = _try_agent_command(phone, "get_status", {"phone": phone})
        if agent_result is not None:
            return agent_result
    status = read_status(phone=phone or None)
    uptime: int | None = None
    if status.get("running") and status.get("started_at"):
        uptime = int(time.time() - status["started_at"])
    return {
        "running": status.get("running", False),
        "jid": status.get("jid"),
        "pid": status.get("pid"),
        "phone": status.get("phone"),
        "started_at": status.get("started_at"),
        "uptime_seconds": uptime,
    }


# ---------------------------------------------------------------------------
# B.0  GET /api/bot/list  — all known bots
# ---------------------------------------------------------------------------

@bot_bp.get("/list")
def get_bot_list():
    """Return status of all known bot accounts."""
    from app.dashboard.utils.bot_status import _pid_alive
    statuses = read_all_statuses()
    result = []
    for s in statuses:
        pid = s.get("pid")
        actually_running = bool(s.get("running") and pid and _pid_alive(pid))
        uptime = None
        if actually_running and s.get("started_at"):
            uptime = int(time.time() - s["started_at"])
        result.append({
            "running": actually_running,
            "jid": s.get("jid"),
            "pid": pid,
            "phone": s.get("phone"),
            "started_at": s.get("started_at"),
            "uptime_seconds": uptime,
        })
    return {"bots": result}


# ---------------------------------------------------------------------------
# B.2  POST /api/bot/login-scan
# ---------------------------------------------------------------------------

@bot_bp.post("/login-scan")
@limiter.limit("5 per minute")
def post_login_scan():
    """
    Launch regwithscan.py as a background subprocess.
    The QR output will be streamed via GET /api/bot/qr-stream.
    """
    global _qr_proc

    # Kill any previous scan process
    _kill_qr_proc()

    script_path = _resolve_script("regwithscan.py")
    if not script_path.exists():
        return {"error": "regwithscan.py not found"}, 404

    try:
        _qr_proc = subprocess.Popen(
            [sys.executable, "-u", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(Path.cwd()),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        _write_pid_file(_qr_proc.pid)
        logger.info("QR scan subprocess started, PID=%s", _qr_proc.pid)
        return {"ok": True, "pid": _qr_proc.pid}
    except OSError as exc:
        logger.error("Failed to start regwithscan.py: %s", exc)
        return {"error": str(exc)}, 500


# ---------------------------------------------------------------------------
# B.3  GET /api/bot/qr-stream
# ---------------------------------------------------------------------------

@bot_bp.get("/qr-stream")
def get_qr_stream():
    """
    SSE stream that pushes QR-code data from the running scan subprocess.

    Event format:
        event: qr
        data: <base64-encoded QR terminal string>  ← one terminal line per event

        event: status
        data: {"type": "login_success"} | {"type": "timeout"} | {"type": "error", "msg": "..."}
    """
    global _qr_proc

    def generate():
        proc = _qr_proc
        if proc is None or proc.poll() is not None:
            yield _sse_event("status", {"type": "error", "msg": "No active scan session"})
            return

        deadline = time.time() + 300  # 5-minute max stream duration
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                if time.time() > deadline:
                    yield _sse_event("status", {"type": "timeout"})
                    break
                line = line.rstrip("\n")
                if not line:
                    continue
                # Detect successful login by looking for JID in output
                if "@" in line and ".net" in line:
                    yield _sse_event("status", {"type": "login_success", "jid": line.strip()})
                    break
                yield _sse_event("qr", line)
        except Exception as exc:
            logger.warning("QR stream error: %s", exc)
            yield _sse_event("status", {"type": "error", "msg": str(exc)})
        finally:
            # Don't kill process here — it may still be verifying login
            pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# B.4  POST /api/bot/login-linkcode
# ---------------------------------------------------------------------------

@bot_bp.post("/login-linkcode")
@limiter.limit("5 per minute")
def post_login_linkcode():
    """
    Launch regwithlinkcode.py; capture and return the generated link code.

    Request body (JSON): {"phone": "+8613812345678"}
    Response:            {"link_code": "ABCD1234"}
    """
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip()
    if not phone:
        return {"error": "phone required"}, 400

    script_path = _resolve_script("regwithlinkcode.py")
    if not script_path.exists():
        return {"error": "regwithlinkcode.py not found"}, 404

    try:
        proc = subprocess.Popen(
            [sys.executable, str(script_path), phone],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1,
            cwd=str(Path.cwd()),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
    except OSError as exc:
        logger.error("Failed to start regwithlinkcode.py: %s", exc)
        return {"error": str(exc)}, 500

    # Read stdout until we see an 8-character link code or process exits
    link_code: str | None = None
    deadline = time.time() + _BOT_STARTUP_TIMEOUT
    for line in proc.stdout:  # type: ignore[union-attr]
        if time.time() > deadline:
            break
        line = line.strip()
        logger.debug("linkcode stdout: %s", line)
        # Link codes are typically 8 alphanumeric characters on their own line
        if len(line) == 8 and line.isalnum():
            link_code = line
            break

    if link_code:
        return {"ok": True, "link_code": link_code}
    else:
        proc.terminate()
        return {"error": "Link code not received within timeout"}, 504


# ---------------------------------------------------------------------------
# B.5  POST /api/bot/logout
# ---------------------------------------------------------------------------

@bot_bp.post("/logout")
@limiter.limit("10 per minute")
def post_logout():
    """Send SIGTERM to a running bot. Body JSON: {phone} (optional)."""
    from app.dashboard.utils.bot_status import clear_status
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip().lstrip("+") or None
    # Try agent first
    if phone:
        try:
            agent_result = _try_agent_command(phone, "stop_bot", {"phone": phone})
        except RuntimeError as exc:
            return {"error": str(exc)}, 503
        if agent_result is not None:
            return agent_result
        if _BOT_DRIVER_MODE == "agent":
            return {"error": f"BOT_DRIVER_MODE=agent but no agent manages phone={phone}"}, 503
    status = read_status(phone=phone)
    pid = status.get("pid")
    if not status.get("running") or not pid:
        return {"error": "Bot is not running"}, 409

    try:
        _terminate_pid(pid)
        logger.info("Sent SIGTERM to bot PID=%s phone=%s", pid, phone)
        clear_status(phone=phone)
        # Also clean up the proc from our dict
        if phone and phone in _start_procs:
            del _start_procs[phone]
        return {"ok": True, "pid": pid}
    except ProcessLookupError:
        clear_status(phone=phone)
        if phone and phone in _start_procs:
            del _start_procs[phone]
        logger.info("Bot PID=%s was already gone; status cleared", pid)
        return {"ok": True, "pid": pid, "note": "process was already stopped"}
    except PermissionError:
        return {"error": "Permission denied terminating process"}, 403


# ---------------------------------------------------------------------------
# B.6  POST /api/bot/start
# ---------------------------------------------------------------------------

@bot_bp.post("/start")
@limiter.limit("5 per minute")
def post_bot_start():
    """
    Start the bot for an already-registered phone number.
    If a connected agent manages this phone, the command is forwarded to it.
    Otherwise falls back to launching a local subprocess.

    Request body (JSON): {"phone": "989334018988"}
    Response:            {"ok": true, "pid": 12345}
    """
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip().lstrip("+")
    if not phone:
        return {"error": "phone required"}, 400
    if not phone.isdigit() or not (7 <= len(phone) <= 15):
        return {"error": "invalid phone number — digits only, 7-15 characters"}, 400

    # Try agent first (agent manages bots on its own machine)
    try:
        agent_result = _try_agent_command(phone, "start_bot", {"phone": phone})
    except RuntimeError as exc:
        return {"error": str(exc)}, 503
    if agent_result is not None:
        return agent_result

    # If mode=agent we should never reach here, but guard anyway
    if _BOT_DRIVER_MODE == "agent":
        return {"error": f"BOT_DRIVER_MODE=agent but no agent manages phone={phone}"}, 503

    # Fall back to local subprocess
    # Refuse to double-start the same phone
    status = read_status(phone=phone)
    if status.get("running") and status.get("pid") and _pid_alive(status["pid"]):
        return {"ok": True, "pid": status["pid"], "already_running": True}

    script_path = _resolve_script("main.py")
    if not script_path.exists():
        return {"error": "script/main.py not found"}, 404

    # Kill any previous proc for this phone so its stdout pipe is freed
    prev = _start_procs.get(phone)
    if prev is not None and prev.poll() is None:
        try:
            prev.terminate()
        except OSError:
            pass

    try:
        proc = subprocess.Popen(
            [sys.executable, str(script_path), phone],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1,
            cwd=str(Path.cwd()),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        _start_procs[phone] = proc
        _write_pid_file(proc.pid)
        logger.info("Bot start subprocess launched, PID=%s, phone=%s", proc.pid, phone)
        return {"ok": True, "pid": proc.pid}
    except OSError as exc:
        logger.error("Failed to start script/main.py: %s", exc)
        return {"error": str(exc)}, 500


# ---------------------------------------------------------------------------
# B.7  GET /api/bot/start-stream
# ---------------------------------------------------------------------------

@bot_bp.get("/start-stream")
def get_start_stream():
    """
    SSE stream for a specific bot's startup progress.
    Query params: phone (required), token (auth)
    """
    phone = request.args.get("phone", "").strip().lstrip("+")

    token = request.args.get("token", "")
    from app.dashboard.api.auth import check_bearer
    if token:
        import flask
        flask.request.environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"

    def generate():
        proc = _start_procs.get(phone) if phone else None
        if proc is None:
            # Bot may have been started outside the dashboard or in a previous server session.
            # If it's already running per status file, emit connected immediately.
            st = read_status(phone=phone or None)
            if st.get("running") and st.get("pid") and _pid_alive(st["pid"]):
                yield _sse_event("status", {
                    "type": "connected",
                    "jid": st.get("jid"),
                    "pid": st.get("pid"),
                    "phone": phone,
                })
            else:
                yield _sse_event("status", {"type": "error", "msg": "No active start session for this phone"})
            return

        deadline = time.time() + _BOT_CONNECT_TIMEOUT
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                if time.time() > deadline:
                    yield _sse_event("status", {"type": "timeout",
                                                 "msg": "Bot did not connect within timeout"})
                    _start_drain_thread(proc)
                    return
                line = line.rstrip("\n")
                if line:
                    yield _sse_event("log", line)
                # Check if bot is now connected
                st = read_status(phone=phone or None)
                if st.get("running") and st.get("pid") == proc.pid:
                    yield _sse_event("status", {
                        "type": "connected",
                        "jid": st.get("jid"),
                        "pid": st.get("pid"),
                        "phone": phone,
                    })
                    _start_drain_thread(proc)
                    return
        except Exception as exc:
            logger.warning("start-stream error: %s", exc)
            yield _sse_event("status", {"type": "error", "msg": str(exc)})
            _start_drain_thread(proc)
            return

        # Process exited — report outcome
        rc = proc.poll()
        if rc == 0:
            st = read_status(phone=phone or None)
            if st.get("running"):
                yield _sse_event("status", {
                    "type": "connected",
                    "jid": st.get("jid"),
                    "pid": st.get("pid"),
                    "phone": phone,
                })
            else:
                yield _sse_event("status", {"type": "error",
                                             "msg": f"Process exited (code {rc}) without connecting"})
        else:
            yield _sse_event("status", {"type": "error",
                                         "msg": f"Process exited with code {rc}"})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _start_drain_thread(proc: "subprocess.Popen") -> None:
    """Start a daemon thread that drains proc.stdout until the process exits.

    Draining prevents the OS pipe buffer (typically 64 KB on Windows) from
    filling up and blocking the bot.  Log lines are NOT forwarded to the
    WebSocket room here — the file-tail loop in websocket.py already reads
    logs/zowsup.log, so forwarding stdout would cause every line to appear
    twice (bot writes to both StreamHandler and FileHandler simultaneously).
    """
    if proc is None or proc.stdout is None:
        return

    def _drain():
        try:
            for _ in proc.stdout:
                pass  # consume to prevent pipe-buffer stall; do not re-emit
        except Exception:
            pass

    t = threading.Thread(target=_drain, daemon=True, name=f"bot-stdout-drain-{proc.pid}")
    t.start()
    logger.debug("Started stdout drain thread for bot PID=%s", proc.pid)


def _resolve_script(name: str) -> Path:
    """Return absolute path to script/<name>."""
    return Path.cwd() / "script" / name


def _write_pid_file(pid: int) -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _kill_qr_proc() -> None:
    global _qr_proc
    if _qr_proc is not None and _qr_proc.poll() is None:
        try:
            _qr_proc.terminate()
        except OSError:
            pass
        _qr_proc = None


def _terminate_pid(pid: int) -> None:
    """Send SIGTERM on POSIX; use taskkill on Windows."""
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
        )
        if result.returncode != 0:
            # Exit code 128 = process not found; treat as already gone.
            raise ProcessLookupError(f"taskkill failed (code {result.returncode}): PID {pid} not found")
    else:
        os.kill(pid, signal.SIGTERM)


def _sse_event(event: str, data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# Helpers: failed-account tracking
# ---------------------------------------------------------------------------

_FAILED_FILE = Path("data") / "bot_failed.json"


def _read_failed() -> dict:
    """Return {phone: iso_timestamp} dict."""
    try:
        return json.loads(_FAILED_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_failed(data: dict) -> None:
    _FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FAILED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def mark_phone_failed(phone: str) -> None:
    """Record phone as permanently-failed (called from zowbot_layer on 40x)."""
    import datetime
    failed = _read_failed()
    failed[phone] = datetime.datetime.utcnow().isoformat()
    _write_failed(failed)


# ---------------------------------------------------------------------------
# B.8  GET /api/bot/accounts
# ---------------------------------------------------------------------------

@bot_bp.get("/accounts")
def list_accounts():
    """
    Return a list of all imported bot accounts found under ACCOUNT_PATH.

    Each entry:
        phone       (str)   directory name / phone number
        pushname    (str|null) from stored config
        is_running  (bool)  matches current bot_status.json JID
        is_failed   (bool)  listed in data/bot_failed.json
        failed_at   (str|null) ISO timestamp of last failure
    """
    try:
        from conf.constants import SysVar
        SysVar.loadConfig()
        account_path = Path(SysVar.ACCOUNT_PATH)
    except Exception as exc:
        logger.warning("Cannot load SysVar: %s", exc)
        return {"error": str(exc)}, 500

    all_statuses = read_all_statuses()
    running_phones = {
        s.get("phone", "")
        for s in all_statuses
        if s.get("running") and s.get("pid") and _pid_alive(s["pid"])
    }

    # Merge agent-reported running phones; also collect all agent-managed phones
    agent_phones: dict[str, str] = {}  # phone -> agent_id (ALL registered, not just running)
    try:
        from app.dashboard.api.agent_gateway import (
            get_agent_for_phone,
            get_agent_running_phones,
            get_all_agent_phones,
            get_agent_phone_status,
        )
        agent_running = get_agent_running_phones()
        running_phones |= agent_running
        agent_phones = get_all_agent_phones()
        _has_agent_info = True
    except Exception:
        get_agent_for_phone = lambda _: None  # noqa: E731
        get_agent_phone_status = lambda _: None  # noqa: E731
        _has_agent_info = False

    failed = _read_failed()

    accounts = []
    if account_path.exists():
        for entry in account_path.iterdir():
            if not entry.is_dir():
                continue
            phone = entry.name
            # Skip temp/hidden dirs
            if phone.startswith(".") or phone == "tmp":
                continue

            pushname = None
            try:
                from core.config.manager import ConfigManager
                cfg = ConfigManager().load(str(entry))
                if cfg:
                    pushname = getattr(cfg, "pushname", None)
            except Exception:
                pass

            try:
                import datetime as _dt
                last_seen = _dt.datetime.utcfromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                last_seen = None

            accounts.append({
                "phone": phone,
                "pushname": pushname,
                "is_running": (phone in running_phones),
                "is_failed": (phone in failed),
                "failed_at": failed.get(phone),
                "last_seen": last_seen,
                "agent_id": get_agent_for_phone(phone) if _has_agent_info else None,
            })

    # Append phones that are managed by agents but have no local account directory
    if _has_agent_info and agent_phones:
        local_phones = {a["phone"] for a in accounts}
        for ph, aid in agent_phones.items():
            if ph in local_phones:
                continue
            st = get_agent_phone_status(ph) or {}
            # Derive a display name from the JID if available (e.g. "6281234@s.whatsapp.net" → "6281234")
            jid = st.get("jid") or ""
            pushname = jid.split("@")[0] if jid else None
            accounts.append({
                "phone": ph,
                "pushname": pushname,
                "is_running": bool(st.get("running")),
                "is_failed": (ph in failed),
                "failed_at": failed.get(ph),
                "last_seen": None,
                "agent_id": aid,
            })

    # Sort by last_seen descending (most recently touched first)
    accounts.sort(key=lambda a: a["last_seen"] or "", reverse=True)

    return {"accounts": accounts}


# ---------------------------------------------------------------------------
# B.9  DELETE /api/bot/accounts/<phone>
# ---------------------------------------------------------------------------

@bot_bp.delete("/accounts/<phone>")
@limiter.limit("20 per minute")
def delete_account(phone: str):
    """Permanently delete the account directory for the given phone number."""
    import shutil

    # Validate phone — digits only
    if not phone.isdigit() or not (7 <= len(phone) <= 15):
        return {"error": "invalid phone"}, 400

    try:
        from conf.constants import SysVar
        SysVar.loadConfig()
        account_path = Path(SysVar.ACCOUNT_PATH) / phone
    except Exception as exc:
        return {"error": str(exc)}, 500

    if not account_path.exists():
        return {"error": "Account not found"}, 404

    # Refuse if it's the currently running bot
    status = read_status()
    running_jid = status.get("jid") or ""
    running_phone = running_jid.split("@")[0]
    if status.get("running") and running_phone == phone:
        return {"error": "Cannot delete the currently running bot — stop it first"}, 409

    try:
        shutil.rmtree(str(account_path))
        logger.info("Deleted account directory: %s", account_path)
    except OSError as exc:
        return {"error": str(exc)}, 500

    # Also remove from failed list
    failed = _read_failed()
    failed.pop(phone, None)
    _write_failed(failed)

    return {"ok": True, "phone": phone}


# ---------------------------------------------------------------------------
# B.10  PATCH /api/bot/accounts/<phone>/mark-failed
# ---------------------------------------------------------------------------

@bot_bp.patch("/accounts/<phone>/mark-failed")
@limiter.limit("30 per minute")
def toggle_mark_failed(phone: str):
    """Toggle the failed-login mark for a given phone."""
    if not phone.replace("+", "").isdigit() or not (7 <= len(phone.lstrip("+")) <= 15):
        return {"error": "invalid phone"}, 400

    failed = _read_failed()
    if phone in failed:
        failed.pop(phone)
        is_failed = False
    else:
        import datetime
        failed[phone] = datetime.datetime.utcnow().isoformat()
        is_failed = True
    _write_failed(failed)
    return {"phone": phone, "is_failed": is_failed}


# ---------------------------------------------------------------------------
# B.11  DELETE /api/bot/accounts  (batch delete failed)
# ---------------------------------------------------------------------------

@bot_bp.delete("/accounts")
@limiter.limit("5 per minute")
def delete_failed_accounts():
    """Delete all accounts marked as failed."""
    import shutil

    try:
        from conf.constants import SysVar
        SysVar.loadConfig()
        account_path = Path(SysVar.ACCOUNT_PATH)
    except Exception as exc:
        return {"error": str(exc)}, 500

    failed = _read_failed()
    if not failed:
        return {"deleted": []}

    status = read_status()
    running_jid = status.get("jid") or ""
    running_phone = running_jid.split("@")[0]

    deleted, skipped = [], []
    for phone in list(failed.keys()):
        if status.get("running") and running_phone == phone:
            skipped.append(phone)
            continue
        target = account_path / phone
        if target.exists():
            try:
                shutil.rmtree(str(target))
                deleted.append(phone)
                failed.pop(phone)
            except OSError as exc:
                logger.warning("Could not delete %s: %s", target, exc)
                skipped.append(phone)
        else:
            failed.pop(phone)
            deleted.append(phone)

    _write_failed(failed)
    return {"deleted": deleted, "skipped": skipped}


# ---------------------------------------------------------------------------
# B.12  POST /api/bot/import
# ---------------------------------------------------------------------------

@bot_bp.post("/import")
@limiter.limit("10 per minute")
def import_account():
    """
    Import one or more 6-segment bot strings.

    Request body:
        {
          "lines":    ["phone,pk1,sk1,pk2,sk2,sixth", ...],
          "agent_id": "pc"   ← optional; if provided, the import runs on that agent
        }

    When agent_id is given, the lines are dispatched to the agent via WebSocket
    and the agent runs import6.py on its own machine.
    When agent_id is absent, import6.py is executed locally on the server.
    """
    body = request.get_json(silent=True) or {}
    lines = [str(l).strip() for l in body.get("lines", []) if str(l).strip()]
    if not lines:
        return {"error": "lines (list) required"}, 400

    agent_id = str(body.get("agent_id", "")).strip() or None

    # ── Remote import via agent ──────────────────────────────────────────────
    if agent_id:
        try:
            from app.dashboard.api.agent_gateway import dispatch_command
        except ImportError:
            return {"error": "agent_gateway not available"}, 500

        result = dispatch_command(agent_id, "import_account", {"lines": lines},
                                  timeout=max(30.0, len(lines) * 30.0))
        if result is None:
            return {"error": f"Agent '{agent_id}' is not connected or did not respond"}, 503
        if not result.get("ok"):
            return {"error": result.get("error", "import failed on agent")}, 502
        return {
            "imported": result.get("imported", 0),
            "total": result.get("total", len(lines)),
            "results": result.get("results", []),
        }

    # ── Local import ─────────────────────────────────────────────────────────
    script_path = _resolve_script("import6.py")
    if not script_path.exists():
        return {"error": "script/import6.py not found"}, 404

    results = []
    for line in lines:
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path), line],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )
            ok = proc.returncode == 0
            results.append({
                "line": line[:20] + "...",
                "ok": ok,
                "stdout": proc.stdout.strip()[:500] if proc.stdout else "",
                "stderr": proc.stderr.strip()[:200] if proc.stderr else "",
            })
            if ok:
                phone = line.split(",")[0] if "," in line else "?"
                logger.info("Imported account: %s", phone)
        except subprocess.TimeoutExpired:
            results.append({"line": line[:20] + "...", "ok": False, "stderr": "timeout"})
        except Exception as exc:
            results.append({"line": line[:20] + "...", "ok": False, "stderr": str(exc)})

    success = sum(1 for r in results if r["ok"])
    return {"imported": success, "total": len(results), "results": results}


# ---------------------------------------------------------------------------
# B.13  POST /api/bot/export
# ---------------------------------------------------------------------------

@bot_bp.post("/export")
@limiter.limit("10 per minute")
def export_accounts():
    """
    Export 6-segment strings for given phones.

    Request body:  {"phones": ["86xxxxxxxxxx", ...]}
    Response:      {"lines": ["phone,pk1,sk1,pk2,sk2,sixth", ...]}
    """
    body = request.get_json(silent=True) or {}
    phones = body.get("phones", [])
    if not phones or not isinstance(phones, list):
        return {"error": "phones (list) required"}, 400

    script_path = _resolve_script("export6.py")
    if not script_path.exists():
        return {"error": "script/export6.py not found"}, 404

    lines = []
    errors = []
    for phone in phones:
        phone = str(phone).strip().lstrip("+")
        if not phone.isdigit():
            errors.append({"phone": phone, "error": "invalid phone"})
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path), phone],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                lines.append(proc.stdout.strip())
            else:
                errors.append({"phone": phone, "error": proc.stderr.strip()[:200] or "no output"})
        except subprocess.TimeoutExpired:
            errors.append({"phone": phone, "error": "timeout"})
        except Exception as exc:
            errors.append({"phone": phone, "error": str(exc)})

    return {"lines": lines, "errors": errors}
