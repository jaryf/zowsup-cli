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

@bot_bp.get("/status")
def get_bot_status():
    """Return running state of a single bot (query ?phone=X) or legacy single-bot."""
    phone = request.args.get("phone", "").strip().lstrip("+")
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
    statuses = read_all_statuses()
    result = []
    for s in statuses:
        uptime = None
        if s.get("running") and s.get("started_at"):
            uptime = int(time.time() - s["started_at"])
        result.append({
            "running": s.get("running", False),
            "jid": s.get("jid"),
            "pid": s.get("pid"),
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
    Equivalent to running: python script/main.py <phone>

    Request body (JSON): {"phone": "989334018988"}
    Response:            {"ok": true, "pid": 12345}
    """
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip().lstrip("+")
    if not phone:
        return {"error": "phone required"}, 400
    if not phone.isdigit() or not (7 <= len(phone) <= 15):
        return {"error": "invalid phone number — digits only, 7-15 characters"}, 400

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

    Request body:  {"lines": ["phone,pk1,sk1,pk2,sk2,sixth", ...]}
    """
    body = request.get_json(silent=True) or {}
    lines = body.get("lines", [])
    if not lines or not isinstance(lines, list):
        return {"error": "lines (list) required"}, 400

    script_path = _resolve_script("import6.py")
    if not script_path.exists():
        return {"error": "script/import6.py not found"}, 404

    results = []
    for line in lines:
        line = str(line).strip()
        if not line:
            continue
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
