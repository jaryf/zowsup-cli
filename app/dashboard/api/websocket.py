"""
WebSocket event handlers (Flask-SocketIO, async_mode='threading').

Architecture constraint: NO eventlet / gevent.
The 'threading' async_mode is the only safe choice given the project's
asyncio bot process running in a separate process.

Server → Client events:
    new_message      {jid, message: {id, direction, content, message_type, timestamp}}
    profile_updated  {jid, profile: {...}}
    strategy_applied {jid|null, strategy: {...}}

Client → Server events:
    subscribe_user   {jid}   — join room 'user:<jid>'
    unsubscribe_user {jid}   — leave room

Background monitor:
    Polls chat_messages every 2 s; emits new_message to the correct room
    for any rows inserted since last check.
"""

import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import so the rest of the app starts even if flask-socketio
# is not installed.
# ---------------------------------------------------------------------------
try:
    from flask_socketio import SocketIO, join_room, leave_room
    _SOCKETIO_AVAILABLE = True
except ImportError:
    _SOCKETIO_AVAILABLE = False
    logger.warning("flask-socketio not installed — WebSocket features disabled")

# Module-level singleton; populated by init_socketio().
socketio: Optional["SocketIO"] = None

_monitor_thread: Optional[threading.Thread] = None
_monitor_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Bot log streaming — per-bot tail of logs/<phone>.log
# ---------------------------------------------------------------------------

_LOG_MAX_BUFFER = 500  # ring buffer entries kept per bot
_LOGS_DIR = Path("logs")

# per-bot state  {bot_id: list}  /  {bot_id: Thread}
_bot_log_buffers: dict = {}          # bot_id -> list[entry]
_bot_log_buffers_lock = threading.Lock()
_bot_tail_threads: dict = {}         # bot_id -> Thread
_bot_tail_threads_lock = threading.Lock()

# Matches lines written by ShortenedNameFormatter:
# [2026-05-06 14:46:42] logger_name              INFO     [file.py:12] message
_LOG_LINE_RE = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2}))\]\s+(\S+)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(?:\[\S+:\d+\]\s+)?(.+)$'
)


def _parse_log_line(line: str) -> Optional[dict]:
    """Return a structured entry dict or None if the line cannot be parsed."""
    m = _LOG_LINE_RE.match(line.rstrip())
    if not m:
        return None
    return {
        "ts": m.group(2),       # HH:MM:SS
        "level": m.group(4),
        "logger": m.group(3),
        "message": m.group(5),
    }


def _push_log_entry(entry: dict, bot_id: str) -> None:
    """Buffer and emit a single log entry; entry gains a bot_id field."""
    entry = {**entry, "bot_id": bot_id}
    with _bot_log_buffers_lock:
        buf = _bot_log_buffers.setdefault(bot_id, [])
        buf.append(entry)
        if len(buf) > _LOG_MAX_BUFFER:
            buf.pop(0)
    if socketio is not None:
        # broadcast to "logs" (all-bots subscribers) and "logs:<bot_id>" (single-bot subscribers)
        socketio.emit("bot_log", entry, room="logs")
        socketio.emit("bot_log", entry, room=f"logs:{bot_id}")


def _tail_log_file_loop(log_path: Path, bot_id: str) -> None:
    """
    Background daemon: tail a single bot's log file and push new lines.
    Exits cleanly when the file is absent for >30 consecutive seconds.
    """
    last_inode = None
    last_size = 0
    fh = None
    absent_count = 0

    while True:
        time.sleep(0.5)
        try:
            if not log_path.exists():
                if fh:
                    fh.close()
                    fh = None
                last_inode = None
                last_size = 0
                absent_count += 1
                if absent_count > 60:  # ~30 s absent
                    logger.debug("Log file gone, stopping tail thread for %s", bot_id)
                    with _bot_tail_threads_lock:
                        _bot_tail_threads.pop(bot_id, None)
                    return
                continue
            absent_count = 0

            stat = log_path.stat()
            cur_inode = stat.st_ino if hasattr(stat, 'st_ino') else 0
            cur_size = stat.st_size

            # Detect rotation: file shrank or inode changed
            if fh is None or cur_inode != last_inode or cur_size < last_size:
                if fh:
                    fh.close()
                fh = open(log_path, 'r', encoding='utf-8', errors='replace')
                fh.seek(0, 2)  # seek to end
                last_inode = cur_inode
                last_size = cur_size
                continue

            # Read any new lines
            for raw in fh:
                entry = _parse_log_line(raw)
                if entry:
                    _push_log_entry(entry, bot_id)
            last_size = log_path.stat().st_size
        except Exception:
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
            fh = None


def _ensure_tail_threads() -> None:
    """Scan logs/*.log and start a tail thread for each bot log file not yet tracked."""
    if not _LOGS_DIR.exists():
        return
    for log_file in _LOGS_DIR.glob("*.log"):
        bot_id = log_file.stem
        with _bot_tail_threads_lock:
            existing = _bot_tail_threads.get(bot_id)
            if existing and existing.is_alive():
                continue
            t = threading.Thread(
                target=_tail_log_file_loop,
                args=(log_file, bot_id),
                daemon=True,
                name=f"ws-log-tail-{bot_id}",
            )
            _bot_tail_threads[bot_id] = t
            t.start()
            logger.info("Log-tail thread started for bot %s", bot_id)


def _bot_watcher_loop() -> None:
    """Periodically scan for new bot log files and spin up tail threads."""
    while True:
        try:
            _ensure_tail_threads()
        except Exception:
            pass
        time.sleep(5)


# ---------------------------------------------------------------------------
# App-factory integration
# ---------------------------------------------------------------------------

def init_socketio(app) -> Optional["SocketIO"]:
    """
    Create a SocketIO instance and attach it to the Flask app.

    Returns the SocketIO object (or None if unavailable).
    Must be called before socketio.run() in run_dashboard.py.
    In TESTING mode SocketIO is still initialised so test_client() works;
    only the background monitor thread is suppressed.
    """
    global socketio

    if not _SOCKETIO_AVAILABLE:
        return None

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",   # no eventlet / gevent — compatible with asyncio bot
        logger=False,
        engineio_logger=False,
    )
    _register_events(socketio)
    logger.info("Flask-SocketIO initialised (async_mode=threading)")
    return socketio


# ---------------------------------------------------------------------------
# Client → Server event handlers
# ---------------------------------------------------------------------------

def _register_events(sio: "SocketIO") -> None:

    @sio.on("connect")
    def on_connect():
        # All clients join the global room to receive new-contact notifications
        join_room("global")
        logger.debug("WebSocket client connected")

    @sio.on("disconnect")
    def on_disconnect():
        logger.debug("WebSocket client disconnected")

    @sio.on("subscribe_logs")
    def on_subscribe_logs(data=None):
        """
        Subscribe to bot log events.
        data: {"bot_id": "phone_number"} or empty/None for all bots.
        """
        bot_id = ((data or {}).get("bot_id") or "").strip() if isinstance(data, dict) else ""
        if bot_id:
            join_room(f"logs:{bot_id}")
            with _bot_log_buffers_lock:
                snapshot = list(_bot_log_buffers.get(bot_id, []))
            sio.emit("bot_log_snapshot", snapshot)
            logger.debug("WS client subscribed to logs for bot %s", bot_id)
        else:
            join_room("logs")
            with _bot_log_buffers_lock:
                # Merge all buffers sorted by ts
                all_entries = []
                for buf in _bot_log_buffers.values():
                    all_entries.extend(buf)
            all_entries.sort(key=lambda e: e.get("ts", ""))
            sio.emit("bot_log_snapshot", all_entries[-_LOG_MAX_BUFFER:])
            logger.debug("WS client subscribed to all-bots logs room")

    @sio.on("unsubscribe_logs")
    def on_unsubscribe_logs(data=None):
        bot_id = ((data or {}).get("bot_id") or "").strip() if isinstance(data, dict) else ""
        if bot_id:
            leave_room(f"logs:{bot_id}")
        else:
            leave_room("logs")
        logger.debug("WS client unsubscribed from logs (bot_id=%s)", bot_id or "all")

    @sio.on("subscribe_user")
    def on_subscribe_user(data):
        jid = (data or {}).get("jid", "")
        if jid:
            join_room(f"user:{jid}")
            logger.debug("WS client subscribed to room user:%s", jid)

    @sio.on("unsubscribe_user")
    def on_unsubscribe_user(data):
        jid = (data or {}).get("jid", "")
        if jid:
            leave_room(f"user:{jid}")
            logger.debug("WS client unsubscribed from room user:%s", jid)


# ---------------------------------------------------------------------------
# Background DB-monitor → emit loop
# ---------------------------------------------------------------------------

def start_monitor_thread(db_path: str) -> None:
    """
    Start the background thread that polls for new chat_messages and emits
    new_message WebSocket events.  Idempotent — safe to call multiple times.
    """
    global _monitor_thread
    if os.environ.get("TESTING") or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _monitor_lock:
        if not (_monitor_thread and _monitor_thread.is_alive()):
            _monitor_thread = threading.Thread(
                target=_monitor_loop,
                args=(db_path,),
                daemon=True,
                name="ws-db-monitor",
            )
            _monitor_thread.start()
            logger.info("WebSocket DB-monitor thread started (poll interval: 2 s)")

        # Start the bot-log watcher (scans for new *.log files periodically)
        _watcher_running = any(
            t.name == "ws-bot-watcher" and t.is_alive()
            for t in threading.enumerate()
        )
        if not _watcher_running:
            watcher = threading.Thread(
                target=_bot_watcher_loop,
                daemon=True,
                name="ws-bot-watcher",
            )
            watcher.start()
            logger.info("WebSocket bot-log watcher thread started")

        # Immediately scan once so existing log files are tailed right away
        _ensure_tail_threads()


def _monitor_loop(db_path: str) -> None:
    """Poll for new rows; emit new_message for each one found."""
    last_id = _latest_message_id(db_path)
    while True:
        time.sleep(2)
        try:
            if socketio is None:
                continue
            new_rows = _fetch_new_messages(db_path, last_id)
            for row in new_rows:
                last_id = max(last_id, row["id"])
                emit_new_message(row)
            # Check for bot-triggered avatar updates (SetPicture notifications)
            _flush_avatar_updates()
        except Exception:
            logger.exception("WebSocket monitor error")


def _latest_message_id(db_path: str) -> int:
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        val = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM chat_messages"
        ).fetchone()[0]
        conn.close()
        return val
    except Exception:
        return 0


def _fetch_new_messages(db_path: str, after_id: int) -> list:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, user_jid, bot_jid, direction, content, message_type, timestamp, participant, notify, media_path, source "
        "FROM chat_messages WHERE id > ? ORDER BY id ASC LIMIT 50",
        (after_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Server → Client emit helpers
# (callable from routes, scheduler callbacks, etc.)
# ---------------------------------------------------------------------------

def emit_new_message(msg: dict) -> None:
    """Emit new_message to the user:<jid> room and the global room."""
    if socketio is None:
        return
    jid = msg.get("user_jid", "")
    payload = {
        "jid": jid,
        "message": {
            "id": msg["id"],
            "user_jid": jid,
            "bot_jid": msg.get("bot_jid"),
            "direction": msg["direction"],
            "content": msg["content"],
            "message_type": msg.get("message_type", "text"),
            "timestamp": msg.get("timestamp"),
            "created_at": msg.get("created_at", ""),
            "participant": msg.get("participant"),
            "notify": msg.get("notify"),
            "media_path": msg.get("media_path"),
            "source": msg.get("source"),
        },
    }
    # Emit to the per-user room (subscribers see it) AND global (for contact-list updates)
    socketio.emit("new_message", payload, room=f"user:{jid}")
    socketio.emit("new_message", payload, room="global")


def emit_strategy_applied(jid: Optional[str], strategy: dict) -> None:
    """
    Emit strategy_applied.
    If jid is None → broadcast to all connected clients (global strategy change).
    """
    if socketio is None:
        return
    payload = {"jid": jid, "strategy": strategy}
    if jid:
        socketio.emit("strategy_applied", payload, room=f"user:{jid}")
    else:
        socketio.emit("strategy_applied", payload)


def emit_profile_updated(jid: str, profile: dict) -> None:
    """Emit profile_updated to the user's room."""
    if socketio is None:
        return
    socketio.emit(
        "profile_updated",
        {"jid": jid, "profile": profile},
        room=f"user:{jid}",
    )


def emit_avatar_updated(jid: str, avatar_url: str) -> None:
    """Emit avatar_updated to all connected clients (global room)."""
    if socketio is None:
        return
    socketio.emit("avatar_updated", {"jid": jid, "avatar_url": avatar_url}, room="global")


def _flush_avatar_updates() -> None:
    """Read pending avatar updates written by the bot process and emit SocketIO events."""
    try:
        from app.dashboard.utils.avatar_queue import pop_avatar_updates
        updates = pop_avatar_updates()
        for jid, url in updates.items():
            emit_avatar_updated(jid, url)
            logger.debug("Emitted avatar_updated for %s", jid)
    except Exception:
        logger.exception("_flush_avatar_updates error")
