"""
app/dashboard/bridge.py
───────────────────────
Central integration point between the zowsup bot core and the dashboard app.

Usage
-----
    from app.dashboard.bridge import dashboard as _db

    _db.save_avatar_url(jid, url)
    _db.write_status(running=True, jid=jid, phone=phone)
    # … all calls are always safe; no-ops when DASHBOARD_MODE is unset.

Behaviour
---------
*DASHBOARD_MODE is NOT set* (standalone bot, ``python script/main.py …``):
    ``dashboard`` is a :class:`_NoDashboard` instance.  Every attribute access
    returns a no-op callable and ``db_path`` is ``None``.  The bot never
    touches dashboard storage.

*DASHBOARD_MODE=1* (set by ``script/dashboard.py`` or inherited by the bot
subprocess launched from the dashboard):
    ``dashboard`` is a live :class:`_Dashboard` instance that delegates to
    the real dashboard utilities.  All calls are individually exception-safe
    so a single failure never crashes the bot.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_ENABLED: bool = bool(os.environ.get("DASHBOARD_MODE"))


# ---------------------------------------------------------------------------
# No-op stub (standalone bot mode)
# ---------------------------------------------------------------------------

class _NoDashboard:
    """Drop-in stub used when DASHBOARD_MODE is not set."""

    db_path: Optional[str] = None

    def get_ai_enabled(self, jid: str) -> bool:  # noqa: ANN001
        """In standalone mode AI is always enabled."""
        return True

    def __getattr__(self, name: str):  # noqa: ANN204
        def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
            return None
        return _noop

# ---------------------------------------------------------------------------
# Live implementation (dashboard mode)
# ---------------------------------------------------------------------------

class _Dashboard:
    """Delegates to real dashboard utilities; every method is exception-safe."""

    def __init__(self) -> None:
        try:
            from app.dashboard.config import CONFIG  # noqa: PLC0415
            self.db_path: Optional[str] = CONFIG.get("DASHBOARD_DB_PATH")
        except Exception as exc:
            logger.warning(
                "Dashboard bridge: failed to load config, disabling dashboard writes (%s)", exc
            )
            self.db_path = None

    # ── Avatar queue ──────────────────────────────────────────────────────

    def dequeue_avatar_requests(self) -> list:
        try:
            from app.dashboard.utils.avatar_queue import dequeue_avatar_requests  # noqa: PLC0415
            return dequeue_avatar_requests() or []
        except Exception as exc:
            logger.debug("bridge.dequeue_avatar_requests failed: %s", exc)
            return []

    def save_avatar_url(self, jid: str, url: str) -> None:
        if not self.db_path:
            return
        try:
            from app.dashboard.utils.avatar_queue import save_avatar_url  # noqa: PLC0415
            save_avatar_url(jid, url, self.db_path)
        except Exception as exc:
            logger.debug("bridge.save_avatar_url failed: %s", exc)

    def notify_avatar_updated(self, jid: str, url: str) -> None:
        try:
            from app.dashboard.utils.avatar_queue import notify_avatar_updated  # noqa: PLC0415
            notify_avatar_updated(jid, url)
        except Exception as exc:
            logger.debug("bridge.notify_avatar_updated failed: %s", exc)

    def save_display_name(self, jid: str, name: str) -> None:
        if not self.db_path:
            return
        try:
            from app.dashboard.utils.avatar_queue import save_display_name  # noqa: PLC0415
            save_display_name(jid, name, self.db_path)
        except Exception as exc:
            logger.debug("bridge.save_display_name failed: %s", exc)

    def save_group_members(
        self,
        group_jid: str,
        participants: dict,
        participant_lids: dict,
    ) -> None:
        if not self.db_path:
            return
        try:
            from app.dashboard.utils.avatar_queue import save_group_members  # noqa: PLC0415
            save_group_members(group_jid, participants, self.db_path, participant_lids)
        except Exception as exc:
            logger.debug("bridge.save_group_members failed: %s", exc)

    # ── Bot status ────────────────────────────────────────────────────────

    def write_status(
        self,
        *,
        running: bool,
        jid: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> None:
        try:
            from app.dashboard.utils.bot_status import write_status  # noqa: PLC0415
            write_status(running=running, jid=jid, phone=phone)
        except Exception as exc:
            logger.debug("bridge.write_status failed: %s", exc)

    def clear_status(self, *, phone: Optional[str] = None) -> None:
        try:
            from app.dashboard.utils.bot_status import clear_status  # noqa: PLC0415
            clear_status(phone=phone)
        except Exception as exc:
            logger.debug("bridge.clear_status failed: %s", exc)

    def mark_phone_failed(self, phone: Optional[str]) -> None:
        if not phone:
            return
        try:
            from app.dashboard.api.bot_control import mark_phone_failed  # noqa: PLC0415
            mark_phone_failed(phone)
        except Exception as exc:
            logger.debug("bridge.mark_phone_failed failed: %s", exc)

    # ── Strategy ──────────────────────────────────────────────────────────

    def get_strategy_manager(self) -> Optional[object]:
        if not self.db_path:
            return None
        try:
            from app.dashboard.strategy.strategy_manager import StrategyManager  # noqa: PLC0415
            return StrategyManager(self.db_path)
        except Exception as exc:
            logger.debug("bridge.get_strategy_manager failed: %s", exc)
            return None

    def get_ai_enabled(self, jid: str) -> bool:
        """Return per-JID AI toggle; if no row yet, fall back to global config.conf default."""
        if not self.db_path:
            return self._global_ai_default()
        try:
            import sqlite3 as _sqlite3  # noqa: PLC0415
            conn = _sqlite3.connect(self.db_path, timeout=3)
            try:
                row = conn.execute(
                    "SELECT ai_enabled FROM ai_settings WHERE jid = ?", (jid,)
                ).fetchone()
                if row is not None:
                    return bool(row[0])
                return self._global_ai_default()
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("bridge.get_ai_enabled failed: %s", exc)
            return self._global_ai_default()

    @staticmethod
    def _global_ai_default() -> bool:
        """Read the global AI enabled flag from conf/config.conf (fallback: True)."""
        try:
            import configparser as _cp  # noqa: PLC0415
            from pathlib import Path as _Path  # noqa: PLC0415
            project_root = _Path(__file__).resolve().parent.parent.parent
            conf = _cp.ConfigParser()
            conf.read(project_root / "conf" / "config.conf", encoding="utf-8")
            return conf.getboolean("AI_LLM_ACTIVE", "enabled", fallback=True)
        except Exception:
            return True

    # ── Chat messages ─────────────────────────────────────────────────────

    def save_chat_message(
        self,
        *,
        bot_jid: str,
        user_jid: str,
        direction: str,
        content: str,
        message_type: str = "text",
        participant: Optional[str] = None,
        notify: Optional[str] = None,
        media_path: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        """Write a chat message row to dashboard.db (local mode)."""
        if not self.db_path or not content:
            return
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(self.db_path, timeout=5)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    "INSERT INTO chat_messages "
                    "(user_jid, direction, content, message_type, timestamp, bot_jid, participant, notify, media_path, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_jid, direction, content, message_type, int(time.time()), bot_jid, participant, notify, media_path, source),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("bridge.save_chat_message failed: %s", exc)


# ---------------------------------------------------------------------------
# Agent bridge  (AGENT_MODE=1 — bot subprocess on remote agent machine)
# ---------------------------------------------------------------------------

class _AgentBridge:
    """
    Used when AGENT_MODE=1.  Forwards message data to the backend server
    via HTTP POST instead of writing to a local SQLite database.

    Authentication
    ──────────────
    Each request carries an X-Agent-Auth header:
        <agent_id>:<signed_at>:<HMAC-SHA256(agent_id:signed_at, secret)>
    Same scheme as the WebSocket connect auth.
    """

    db_path: Optional[str] = None  # no local DB in agent mode

    def __init__(self) -> None:
        self._agent_id = os.environ.get("AGENT_ID", "")
        raw_secret = os.environ.get("AGENT_KEY_SECRET", "")
        self._secret: bytes = (
            bytes.fromhex(raw_secret) if len(raw_secret) == 64 else raw_secret.encode()
        )
        self._backend_url = os.environ.get("AGENT_BACKEND_URL", "").rstrip("/")
        if not self._agent_id or not self._secret or not self._backend_url:
            logger.warning(
                "AgentBridge: AGENT_ID / AGENT_KEY_SECRET / AGENT_BACKEND_URL not fully set; "
                "message forwarding disabled"
            )
            self._enabled = False
        else:
            self._enabled = True

    def _auth_header(self) -> str:
        signed_at = int(time.time())
        sig = hmac.new(
            self._secret,
            f"{self._agent_id}:{signed_at}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{self._agent_id}:{signed_at}:{sig}"

    def save_chat_message(
        self,
        *,
        bot_jid: str,
        user_jid: str,
        direction: str,
        content: str,
        message_type: str = "text",
        participant: Optional[str] = None,
        notify: Optional[str] = None,
        media_path: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        """Forward a chat message to the backend ingest endpoint."""
        if not self._enabled or not content:
            return
        try:
            import urllib.request
            import json as _json
            body = _json.dumps({
                "bot_jid": bot_jid,
                "user_jid": user_jid,
                "direction": direction,
                "content": content,
                "message_type": message_type,
                "participant": participant,
                "notify": notify,
                "media_path": media_path,
                "source": source,
                "timestamp": int(time.time()),
            }).encode()
            req = urllib.request.Request(
                f"{self._backend_url}/api/bot/ingest",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Agent-Auth": self._auth_header(),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status not in (200, 201):
                    logger.debug("AgentBridge ingest status %s", resp.status)
        except Exception as exc:
            logger.debug("AgentBridge.save_chat_message failed: %s", exc)

    # All other bridge calls are no-ops in agent mode
    def __getattr__(self, name: str):  # noqa: ANN204
        def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
            return None
        return _noop


# ---------------------------------------------------------------------------
# Public singleton — import and use this
# ---------------------------------------------------------------------------

_AGENT_MODE: bool = bool(os.environ.get("AGENT_MODE"))

if _AGENT_MODE:
    dashboard: "_Dashboard | _NoDashboard | _AgentBridge" = _AgentBridge()
elif _ENABLED:
    dashboard = _Dashboard()
else:
    dashboard = _NoDashboard()
