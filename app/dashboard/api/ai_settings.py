"""
app/dashboard/api/ai_settings.py
──────────────────────────────────
Per-conversation AI enable/disable (human takeover) API.

Endpoints
---------
GET  /api/ai/settings/<jid>   — return {"jid": str, "ai_enabled": bool}
POST /api/ai/settings/<jid>   — body {"ai_enabled": bool} → return same
"""
import configparser
import logging
import sqlite3
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app.dashboard.api.auth import check_bearer
from app.dashboard.api.rate_limit import limiter

logger = logging.getLogger(__name__)

ai_settings_bp = Blueprint("ai_settings", __name__)


def _check_auth():
    err = check_bearer()
    if err:
        return err
    return None


def _get_db_path() -> str:
    return current_app.config["DASHBOARD_DB_PATH"]


def _global_ai_default() -> bool:
    """Read the global AI enabled flag from conf/config.conf (fallback: True)."""
    try:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        conf = configparser.ConfigParser()
        conf.read(project_root / "conf" / "config.conf", encoding="utf-8")
        return conf.getboolean("AI_LLM_ACTIVE", "enabled", fallback=True)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# GET /api/ai/settings/<jid>
# ---------------------------------------------------------------------------

@ai_settings_bp.route("/settings/<path:jid>", methods=["GET"])
@limiter.limit("120/minute")
def get_ai_settings(jid: str):
    err = _check_auth()
    if err:
        return err

    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            row = conn.execute(
                "SELECT ai_enabled FROM ai_settings WHERE jid = ?", (jid,)
            ).fetchone()
            ai_enabled = bool(row[0]) if row is not None else _global_ai_default()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("get_ai_settings DB error: %s", exc)
        ai_enabled = _global_ai_default()

    return jsonify({"jid": jid, "ai_enabled": ai_enabled})


# ---------------------------------------------------------------------------
# POST /api/ai/settings/<jid>
# ---------------------------------------------------------------------------

@ai_settings_bp.route("/settings/<path:jid>", methods=["POST"])
@limiter.limit("60/minute")
def save_ai_settings(jid: str):
    err = _check_auth()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    if "ai_enabled" not in body:
        return jsonify({"error": "ai_enabled field required"}), 400

    ai_enabled = bool(body["ai_enabled"])
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO ai_settings (jid, ai_enabled) VALUES (?, ?)"
                " ON CONFLICT(jid) DO UPDATE SET ai_enabled = excluded.ai_enabled",
                (jid, int(ai_enabled)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("save_ai_settings DB error: %s", exc)
        return jsonify({"error": "database error"}), 500

    return jsonify({"jid": jid, "ai_enabled": ai_enabled})
