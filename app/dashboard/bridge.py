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

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ENABLED: bool = bool(os.environ.get("DASHBOARD_MODE"))


# ---------------------------------------------------------------------------
# No-op stub (standalone bot mode)
# ---------------------------------------------------------------------------

class _NoDashboard:
    """Drop-in stub used when DASHBOARD_MODE is not set."""

    db_path: Optional[str] = None

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


# ---------------------------------------------------------------------------
# Public singleton — import and use this
# ---------------------------------------------------------------------------

dashboard: "_Dashboard | _NoDashboard" = _Dashboard() if _ENABLED else _NoDashboard()
