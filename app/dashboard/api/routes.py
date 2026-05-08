"""
Dashboard API routes (Blueprint).

Phase 1 endpoints return real data where available, or empty structures
that conform to the final schema so the frontend can be built against them.

Endpoints:
  GET  /api/health          health check
  GET  /api/contacts        list of all known contacts with last-message summary
  GET  /api/user-profile    user portrait (empty in Phase 1, real data in Phase 2)
  GET  /api/chat-history    paginated messages
  GET  /api/statistics      aggregated stats
"""

import logging
import os
from flask import Blueprint, current_app, jsonify, request, send_file, abort

from app.dashboard.utils.db_init import get_db_connection, verify_db
from app.dashboard.api.auth import check_bearer
from app.dashboard.api.rate_limit import limiter
from app.dashboard.api.validators import (
    validate_jid,
    validate_page_params,
    sanitize_str,
)

bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


def _count_online_bots() -> int:
    """Return the number of currently running bots."""
    try:
        from app.dashboard.utils.bot_status import read_all_statuses
        statuses = read_all_statuses()
        return sum(1 for s in statuses if s.get("running"))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Phase 4: Bearer-token auth applied to all routes except /health
# ---------------------------------------------------------------------------

@bp.before_request
def _check_auth():
    """Enforce Bearer-token auth on every endpoint except /health and /media/*."""
    if request.endpoint in ("api.health", "api.serve_media"):
        return None
    return check_bearer()


# ---------------------------------------------------------------------------
# 1.14  GET /api/health
# ---------------------------------------------------------------------------

@bp.route("/health", methods=["GET"])
def health():
    """
    Returns DB status so the operator can verify the service is alive and
    dashboard.db is properly initialised.
    """
    try:
        db_path = current_app.config["DASHBOARD_DB_PATH"]
        db_info = verify_db(db_path)
        all_present = all(v != "MISSING" for v in db_info["tables"].values())
        return jsonify({
            "status": "ok" if all_present else "degraded",
            "journal_mode": db_info["journal_mode"],
            "tables": db_info["tables"],
        }), 200
    except Exception as e:
        logger.exception("Health check failed")
        return jsonify({"status": "error", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# 1.10  GET /api/contacts
# ---------------------------------------------------------------------------

@bp.route("/contacts", methods=["GET"])
def contacts():
    """
    Return all distinct contacts sorted by most recent activity,
    with last-message preview and total message count.

    Response:
      {
        "contacts": [
          {
            "user_jid": "989334018988@s.whatsapp.net",
            "last_message": "...",
            "last_timestamp": 1714300000,
            "message_count": 42
          },
          ...
        ]
      }
    """
    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                cm.user_jid,
                cm.bot_jid,
                cm.content        AS last_message,
                cm.timestamp      AS last_timestamp,
                agg.message_count,
                up.avatar_url,
                up.display_name
            FROM chat_messages cm
            INNER JOIN (
                SELECT user_jid,
                       MAX(id)        AS max_id,
                       COUNT(*)       AS message_count
                FROM   chat_messages
                GROUP  BY user_jid
            ) agg ON cm.id = agg.max_id
            LEFT JOIN user_profiles up ON up.user_jid = cm.user_jid
            ORDER  BY last_timestamp DESC
            """
        ).fetchall()

    contacts = [dict(r) for r in rows]

    # Enqueue avatar fetch for contacts whose avatar is missing or stale
    try:
        from app.dashboard.utils.avatar_queue import enqueue_avatar_request, is_avatar_stale
        for c in contacts:
            if not c.get("avatar_url") or is_avatar_stale(c["user_jid"], db_path):
                enqueue_avatar_request(c["user_jid"])
    except Exception:
        logger.debug("Avatar queue enqueue failed (non-fatal)", exc_info=True)

    return jsonify({"contacts": contacts}), 200


# ---------------------------------------------------------------------------
# GET  /api/contact/avatar?jid=<jid>
# POST /api/contact/avatar/refresh    body: {"jid": "..."}
# ---------------------------------------------------------------------------

@bp.route("/contact/avatar", methods=["GET"])
def get_contact_avatar():
    """Return the cached avatar URL for a single JID."""
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid parameter is required"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT avatar_url, avatar_fetched_at FROM user_profiles WHERE user_jid = ?",
            (jid,),
        ).fetchone()

    if row:
        return jsonify({"jid": jid, "avatar_url": row[0], "fetched_at": row[1]}), 200
    return jsonify({"jid": jid, "avatar_url": None, "fetched_at": None}), 200


@bp.route("/contact/avatar/refresh", methods=["POST"])
@limiter.limit("30 per minute")
def post_contact_avatar_refresh():
    """
    Force-enqueue a fresh avatar fetch for the given JID.

    Body JSON:  {"jid": "989334018988@s.whatsapp.net"}
    Response:   {"ok": true, "jid": "..."}
    """
    body = request.get_json(silent=True) or {}
    jid = (body.get("jid") or "").strip()
    if not jid:
        return jsonify({"error": "jid is required"}), 400

    try:
        from app.dashboard.utils.avatar_queue import enqueue_avatar_request
        enqueue_avatar_request(jid)
    except Exception as exc:
        logger.warning("Avatar enqueue failed for %s: %s", jid, exc)
        return jsonify({"error": "Failed to enqueue avatar refresh"}), 500

    return jsonify({"ok": True, "jid": jid}), 200


# ---------------------------------------------------------------------------
# 1.11  GET /api/user-profile?jid=<jid>
#        PATCH /api/user-profile  — manually override category / style
# ---------------------------------------------------------------------------

@bp.route("/user-profile", methods=["GET"])
def user_profile():
    """
    Return the computed portrait for a given JID.

    Phase 1: reads from user_profiles table (will be empty until Phase 2
    computes the data).  Returns a well-typed empty structure instead of 404
    so the frontend can be developed against a stable schema.

    Query params:
        jid  (required)  WhatsApp JID e.g. 8613800001234@s.whatsapp.net
    """
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid parameter is required"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_jid = ?", (jid,)
        ).fetchone()

    if row is None:
        return jsonify(_empty_profile(jid)), 200

    profile = dict(row)

    # Deserialize TEXT JSON columns stored in SQLite
    import json as _json
    for _col in ("topic_preferences", "trend_7d", "trend_30d", "current_strategy"):
        raw = profile.get(_col)
        if isinstance(raw, str):
            try:
                profile[_col] = _json.loads(raw)
            except (ValueError, TypeError):
                profile[_col] = None

    # Prefer manually set overrides over auto-inferred values
    cat_override   = profile.pop("user_category_override", None)
    style_override = profile.pop("communication_style_override", None)
    if cat_override:
        profile["user_category"]         = cat_override
        profile["user_category_is_manual"] = True
    else:
        profile["user_category_is_manual"] = False
    if style_override:
        profile["communication_style"]         = style_override
        profile["communication_style_is_manual"] = True
    else:
        profile["communication_style_is_manual"] = False
    return jsonify(profile), 200


@bp.route("/user-profile", methods=["PATCH"])
def patch_user_profile():
    """
    Manually override user_category and/or communication_style for a JID.

    Body JSON:
        jid                   (required)
        user_category         (optional)  null clears the override
        communication_style   (optional)  null clears the override
    """
    body = request.get_json(silent=True) or {}
    jid = (body.get("jid") or "").strip()
    if not jid:
        return jsonify({"error": "jid is required"}), 400

    allowed_categories = {"VIP", "regular", "new", "at_risk"}
    allowed_styles     = {"detailed", "concise", "patient", "impatient"}

    cat   = body.get("user_category",       ...)   # Ellipsis = "not provided"
    style = body.get("communication_style", ...)

    if cat is not ... and cat is not None and cat not in allowed_categories:
        return jsonify({"error": f"Invalid user_category: {cat}"}), 400
    if style is not ... and style is not None and style not in allowed_styles:
        return jsonify({"error": f"Invalid communication_style: {style}"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        # Ensure a row exists so UPDATE won't silently no-op
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_jid) VALUES (?)", (jid,)
        )
        if cat is not ...:
            conn.execute(
                "UPDATE user_profiles SET user_category_override = ? WHERE user_jid = ?",
                (cat, jid),
            )
        if style is not ...:
            conn.execute(
                "UPDATE user_profiles SET communication_style_override = ? WHERE user_jid = ?",
                (style, jid),
            )
        conn.commit()

    return jsonify({"ok": True, "jid": jid}), 200


def _empty_profile(jid: str) -> dict:
    return {
        "user_jid": jid,
        "total_interactions": 0,
        "first_seen": None,
        "last_seen": None,
        "user_category": None,
        "user_category_is_manual": False,
        "communication_style": None,
        "communication_style_is_manual": False,
        "topic_preferences": {},
        "satisfaction_score": None,
        "trend_7d": {"dates": [], "counts": []},
        "trend_30d": {"dates": [], "counts": []},
        "current_strategy": None,
        "updated_at": None,
    }


# ---------------------------------------------------------------------------
# 1.12  GET /api/chat-history?jid=<jid>&page=1&page_size=50
# ---------------------------------------------------------------------------

@bp.route("/chat-history", methods=["GET"])
def chat_history():
    """
    Return paginated chat messages for a given JID.

    Query params:
        jid        (required)
        page       (optional, default 1)
        page_size  (optional, default 50, max 200)
    """
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid parameter is required"}), 400

    valid, err, page, page_size = validate_page_params(
        request.args.get("page", 1),
        request.args.get("page_size", 50),
    )
    if not valid:
        return jsonify({"error": err}), 400
    page_size = min(page_size, 200)  # hard cap for chat-history

    offset = (page - 1) * page_size

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE user_jid = ?", (jid,)
        ).fetchone()[0]

        rows = conn.execute(
            "SELECT cm.id, cm.user_jid, cm.bot_jid, cm.direction, cm.content, cm.message_type, "
            "       cm.timestamp, cm.created_at, cm.participant, cm.notify, cm.media_path, at.urgency_level, "
            "       gm.participant_jid AS resolved_jid "
            "FROM chat_messages cm "
            "LEFT JOIN ai_thoughts at ON at.message_id = cm.id "
            "LEFT JOIN group_members gm ON gm.group_jid = cm.user_jid AND gm.participant_lid = cm.participant "
            "WHERE cm.user_jid = ? "
            "ORDER BY cm.timestamp DESC "
            "LIMIT ? OFFSET ?",
            (jid, page_size, offset),
        ).fetchall()

    return jsonify({
        "jid": jid,
        "page": page,
        "page_size": page_size,
        "total": total,
        "messages": [dict(r) for r in rows],
    }), 200


# ---------------------------------------------------------------------------
# 1.14  GET /api/media/<filename>   — serve downloaded media files
# ---------------------------------------------------------------------------

@bp.route("/media/<path:filename>", methods=["GET"])
def serve_media(filename: str):
    """
    Serve a previously downloaded media file from DOWNLOAD_PATH.

    The frontend passes the basename of the file (no path traversal).
    Only files that exist inside DOWNLOAD_PATH are served.
    """
    from conf.constants import SysVar

    download_path = getattr(SysVar, "DOWNLOAD_PATH", None)
    if not download_path:
        abort(503, description="DOWNLOAD_PATH not configured")

    # Resolve and guard against path-traversal
    base = os.path.realpath(download_path)
    target = os.path.realpath(os.path.join(base, filename))
    if not target.startswith(base + os.sep) and target != base:
        abort(400, description="Invalid path")

    if not os.path.isfile(target):
        abort(404, description="Media file not found")

    return send_file(target)


# ---------------------------------------------------------------------------
# 1.13  GET /api/statistics
# ---------------------------------------------------------------------------

@bp.route("/statistics", methods=["GET"])
def statistics():
    """
    Return aggregated dashboard statistics.

    Phase 1: computes live counts from chat_messages table.
    Phase 2 will also populate daily_statistics for trend charts.

    Query params:
        days  (optional, default 30)  look-back window
    """
    try:
        days = max(1, int(request.args.get("days", 30)))
    except ValueError:
        return jsonify({"error": "days must be an integer"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        # Total messages
        total_messages = conn.execute(
            "SELECT COUNT(*) FROM chat_messages "
            "WHERE timestamp >= strftime('%s', 'now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()[0]

        # Incoming / outgoing split
        incoming = conn.execute(
            "SELECT COUNT(*) FROM chat_messages "
            "WHERE direction = 'in' AND timestamp >= strftime('%s', 'now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()[0]

        outgoing = conn.execute(
            "SELECT COUNT(*) FROM chat_messages "
            "WHERE direction = 'out' AND timestamp >= strftime('%s', 'now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()[0]

        # Unique active users
        active_users = conn.execute(
            "SELECT COUNT(DISTINCT user_jid) FROM chat_messages "
            "WHERE timestamp >= strftime('%s', 'now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()[0]

        # Total known users (all time)
        total_users = conn.execute(
            "SELECT COUNT(DISTINCT user_jid) FROM chat_messages"
        ).fetchone()[0]

        # Daily breakdown (last N days)
        daily_rows = conn.execute(
            "SELECT date(timestamp, 'unixepoch') AS day, "
            "       SUM(CASE WHEN direction='in'  THEN 1 ELSE 0 END) AS incoming, "
            "       SUM(CASE WHEN direction='out' THEN 1 ELSE 0 END) AS outgoing "
            "FROM chat_messages "
            "WHERE timestamp >= strftime('%s', 'now', ? || ' days') "
            "GROUP BY day ORDER BY day ASC",
            (f"-{days}",),
        ).fetchall()

    return jsonify({
        "window_days": days,
        "total_messages": total_messages,
        "incoming_messages": incoming,
        "outgoing_messages": outgoing,
        "active_users": active_users,
        "total_users": total_users,
        "online_bots": _count_online_bots(),
        "daily_breakdown": [dict(r) for r in daily_rows],
    }), 200


# ---------------------------------------------------------------------------
# Phase 2  GET /api/user-ai-thoughts?jid=<jid>&page=1&page_size=50
# ---------------------------------------------------------------------------

@bp.route("/user-ai-thoughts", methods=["GET"])
def user_ai_thoughts():
    """
    Return paginated AI thought records for a given JID.

    Query params:
        jid        (required)
        page       (optional, default 1)
        page_size  (optional, default 50, max 200)
    """
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid parameter is required"}), 400

    valid, err, page, page_size = validate_page_params(
        request.args.get("page", 1),
        request.args.get("page_size", 50),
    )
    if not valid:
        return jsonify({"error": err}), 400
    page_size = min(page_size, 200)  # hard cap for ai-thoughts

    offset = (page - 1) * page_size
    db_path = current_app.config["DASHBOARD_DB_PATH"]

    with get_db_connection(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM ai_thoughts WHERE user_jid = ?", (jid,)
        ).fetchone()[0]

        rows = conn.execute(
            """
            SELECT id, message_id, user_jid,
                   intent, confidence, detected_keywords,
                   strategy_selected, strategy_reasoning,
                   tone, response_quality_score, urgency_level, created_at
            FROM ai_thoughts
            WHERE user_jid = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (jid, page_size, offset),
        ).fetchall()

    import json as _json
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["detected_keywords"] = _json.loads(d["detected_keywords"] or "[]")
        except Exception:
            d["detected_keywords"] = []
        results.append(d)

    return jsonify({
        "jid": jid,
        "page": page,
        "page_size": page_size,
        "total": total,
        "thoughts": results,
    }), 200


# ---------------------------------------------------------------------------
# Phase 3  Strategy engine endpoints
# ---------------------------------------------------------------------------

# Allowed field values (mirrors strategy_manager.py constants)
_VALID_RESPONSE_STYLES = {"formal", "casual", "concise", "detailed"}
_VALID_TONES = {"polite", "friendly", "professional", "empathetic", "neutral"}
_VALID_LANGUAGES = {"auto", "zh", "en", "mixed"}


def _validate_strategy_config(config: dict):
    """
    Validate strategy config fields.  Returns (ok: bool, error_msg: str|None).
    Unknown extra keys are silently ignored.
    """
    if not isinstance(config, dict):
        return False, "config must be a JSON object"
    style = config.get("response_style")
    tone = config.get("tone")
    language = config.get("language")
    custom = config.get("custom_instructions")

    if style is not None and style not in _VALID_RESPONSE_STYLES:
        return False, f"response_style must be one of {sorted(_VALID_RESPONSE_STYLES)}"
    if tone is not None and tone not in _VALID_TONES:
        return False, f"tone must be one of {sorted(_VALID_TONES)}"
    if language is not None and language not in _VALID_LANGUAGES:
        return False, f"language must be one of {sorted(_VALID_LANGUAGES)}"
    if custom is not None and not isinstance(custom, str):
        return False, "custom_instructions must be a string"
    return True, None


def _get_strategy_manager(db_path: str):
    from app.dashboard.strategy.strategy_manager import StrategyManager
    return StrategyManager(db_path)


@bp.route("/apply-strategy", methods=["POST"])
@limiter.limit("20/minute")
def apply_strategy():
    """
    Apply (or update) a personal strategy for a specific JID.

    Body JSON:
        jid     (required) WhatsApp JID
        config  (required) strategy config dict
        note    (optional) human-readable note for audit log
    """
    body = request.get_json(silent=True) or {}
    jid = (body.get("jid") or "").strip()
    config = body.get("config")
    note = body.get("note")

    if not jid:
        return jsonify({"error": "jid is required"}), 400
    if config is None:
        return jsonify({"error": "config is required"}), 400

    ok, err = _validate_strategy_config(config)
    if not ok:
        return jsonify({"error": err}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        strategy_id = sm.apply_strategy(jid, config, note=note)
    except Exception as e:
        logger.exception("apply_strategy failed")
        return jsonify({"error": str(e)}), 500

    # Phase 4: emit WebSocket event
    try:
        from app.dashboard.api.websocket import emit_strategy_applied
        emit_strategy_applied(jid, config)
    except Exception:
        pass

    return jsonify({
        "strategy_id": strategy_id,
        "jid": jid,
        "config": config,
        "note": note,
    }), 201


@bp.route("/apply-global-strategy", methods=["POST"])
@limiter.limit("20/minute")
def apply_global_strategy():
    """
    Apply (or update) the global strategy (affects all JIDs unless overridden).

    Body JSON:
        config  (required) strategy config dict
        note    (optional) human-readable note
    """
    body = request.get_json(silent=True) or {}
    config = body.get("config")
    note = body.get("note")

    if config is None:
        return jsonify({"error": "config is required"}), 400

    ok, err = _validate_strategy_config(config)
    if not ok:
        return jsonify({"error": err}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        strategy_id = sm.apply_global_strategy(config, note=note)
    except Exception as e:
        logger.exception("apply_global_strategy failed")
        return jsonify({"error": str(e)}), 500

    # Phase 4: emit WebSocket event (broadcast — global strategy affects all users)
    try:
        from app.dashboard.api.websocket import emit_strategy_applied
        emit_strategy_applied(None, config)
    except Exception:
        pass

    return jsonify({
        "strategy_id": strategy_id,
        "config": config,
        "note": note,
    }), 201


@bp.route("/strategy", methods=["GET"])
def get_strategy():
    """
    Return current active strategy for a JID (personal + global merged).

    Query params:
        jid  (optional) — omit to query global strategy only
    """
    jid = request.args.get("jid", "").strip() or None
    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        raw = sm.get_raw_strategies(jid)
        merged = sm.get_active_strategy(jid)
    except Exception as e:
        logger.exception("get_strategy failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "jid": jid,
        "global_strategy": raw["global"],
        "personal_strategy": raw["personal"],
        "merged_strategy": merged,
    }), 200


@bp.route("/strategy/history", methods=["GET"])
def strategy_history():
    """
    Return strategy application history.

    Query params:
        jid    (optional) — omit for global strategy history
        limit  (optional, default 20, max 100)
    """
    jid = request.args.get("jid", "").strip() or None
    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        history = sm.get_history(jid, limit)
    except Exception as e:
        logger.exception("strategy_history failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({"jid": jid, "history": history}), 200


@bp.route("/strategy/rollback", methods=["POST"])
def strategy_rollback():
    """
    Roll back the current strategy to the previous version.

    Body JSON:
        jid  (optional) — omit to roll back global strategy
    """
    body = request.get_json(silent=True) or {}
    jid = (body.get("jid") or "").strip() or None

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        success = sm.rollback_strategy(jid)
    except Exception as e:
        logger.exception("strategy_rollback failed")
        return jsonify({"error": str(e)}), 500

    if success:
        return jsonify({"success": True, "jid": jid}), 200
    return jsonify({
        "success": False,
        "message": "No active strategy found to roll back",
        "jid": jid,
    }), 409


@bp.route("/strategy/<int:strategy_id>/toggle", methods=["PATCH"])
@limiter.limit("30/minute")
def toggle_strategy(strategy_id: int):
    """
    Toggle is_active for a strategy row.
    When activating: deactivate other active rows of the same scope automatically.
    Returns: {id, is_active}
    """
    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        result = sm.toggle_strategy(strategy_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("toggle_strategy failed")
        return jsonify({"error": str(e)}), 500
    return jsonify(result), 200


@bp.route("/strategy/<int:strategy_id>", methods=["DELETE"])
@limiter.limit("20/minute")
def delete_strategy_row(strategy_id: int):
    """Permanently delete a strategy history row."""
    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        deleted = sm.delete_strategy(strategy_id)
    except Exception as e:
        logger.exception("delete_strategy failed")
        return jsonify({"error": str(e)}), 500
    if not deleted:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify({"success": True, "id": strategy_id}), 200


@bp.route("/strategy/conflicts", methods=["GET"])
def strategy_conflicts():
    """
    Return live conflict detection result for a JID.

    Query params:
        jid   (required) WhatsApp JID
    """
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid is required"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    try:
        sm = _get_strategy_manager(db_path)
        conflicts = sm.detect_conflicts(jid)
    except Exception as e:
        logger.exception("strategy_conflicts failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({"jid": jid, "conflicts": conflicts}), 200


# ---------------------------------------------------------------------------
# GET /api/group-info  — basic info + member list for a group JID
# ---------------------------------------------------------------------------

@bp.route("/group-info", methods=["GET"])
def group_info():
    """
    Return basic info and member list for a group JID.

    Member list is sourced from the ``group_members`` table (populated by
    the bot's avatar-poll task when it calls ``group.info``).  If the table
    has no rows yet for this group, falls back to distinct participants
    observed in ``chat_messages``.

    Query params:
        jid  (required) — must end with @g.us

    Response:
      {
        "jid": "...",
        "display_name": "...",
        "avatar_url": "...",
        "message_count": 42,
        "first_seen": 1700000000,
        "last_seen": 1700001000,
        "synced_at": 1700001000 | null,
        "members": [
          {
            "participant": "...",
            "role": "admin" | null,
            "notify": "...",
            "msg_count": 5,
            "last_seen": 1700000999
          },
          ...
        ]
      }
    """
    jid = request.args.get("jid", "").strip()
    if not jid:
        return jsonify({"error": "jid is required"}), 400
    if not jid.endswith("@g.us"):
        return jsonify({"error": "jid must be a group JID ending with @g.us"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        # Basic aggregated stats from chat history
        stats_row = conn.execute(
            "SELECT COUNT(*) AS message_count, "
            "       MIN(timestamp) AS first_seen, "
            "       MAX(timestamp) AS last_seen "
            "FROM chat_messages WHERE user_jid = ?",
            (jid,),
        ).fetchone()

        # Profile info (display_name, avatar_url) from user_profiles if stored
        profile_row = conn.execute(
            "SELECT display_name, avatar_url FROM user_profiles WHERE user_jid = ?",
            (jid,),
        ).fetchone()

        # ── Member list: prefer group_members (real data from group.info) ──
        gm_rows = conn.execute(
            """
            SELECT
                gm.participant_jid  AS participant,
                gm.participant_lid,
                gm.role,
                gm.synced_at,
                gm.last_seen,
                -- latest notify seen in chat_messages for this member
                -- COALESCE handles LID-mode groups (participant stored as @lid)
                (
                    SELECT cm.notify
                    FROM   chat_messages cm
                    WHERE  cm.user_jid   = ?
                      AND  cm.participant = COALESCE(gm.participant_lid, gm.participant_jid)
                      AND  cm.notify IS NOT NULL
                    ORDER  BY cm.timestamp DESC
                    LIMIT  1
                ) AS notify,
                -- message count in this group
                (
                    SELECT COUNT(*)
                    FROM   chat_messages cm
                    WHERE  cm.user_jid   = ?
                      AND  cm.participant = COALESCE(gm.participant_lid, gm.participant_jid)
                ) AS msg_count
            FROM group_members gm
            WHERE gm.group_jid = ?
            ORDER BY
                CASE WHEN gm.role = 'admin' THEN 0 ELSE 1 END,
                msg_count DESC
            """,
            (jid, jid, jid),
        ).fetchall()

        synced_at = None
        if gm_rows:
            synced_at = max((r["synced_at"] for r in gm_rows), default=None)
            members = [dict(r) for r in gm_rows]
            # drop internal columns that are not needed per-member
            for m in members:
                m.pop("synced_at", None)
                m.pop("participant_lid", None)
                m.pop("msg_count", None)
        else:
            # Fallback: derive members from chat_messages participants
            fallback_rows = conn.execute(
                """
                SELECT
                    cm.participant,
                    NULL AS role,
                    (
                        SELECT cm2.notify
                        FROM   chat_messages cm2
                        WHERE  cm2.user_jid   = cm.user_jid
                          AND  cm2.participant = cm.participant
                          AND  cm2.notify IS NOT NULL
                        ORDER  BY cm2.timestamp DESC
                        LIMIT  1
                    ) AS notify,
                    COUNT(*)          AS msg_count,
                    MAX(cm.timestamp) AS last_seen
                FROM chat_messages cm
                WHERE cm.user_jid = ?
                  AND cm.participant IS NOT NULL
                GROUP BY cm.participant
                ORDER BY msg_count DESC
                """,
                (jid,),
            ).fetchall()
            members = [dict(r) for r in fallback_rows]

    return jsonify({
        "jid": jid,
        "display_name": profile_row["display_name"] if profile_row else None,
        "avatar_url": profile_row["avatar_url"] if profile_row else None,
        "message_count": stats_row["message_count"] if stats_row else 0,
        "first_seen": stats_row["first_seen"] if stats_row else None,
        "last_seen": stats_row["last_seen"] if stats_row else None,
        "synced_at": synced_at,
        "members": members,
    }), 200


# ---------------------------------------------------------------------------
# 404 / 405 handlers
# ---------------------------------------------------------------------------

@bp.app_errorhandler(404)
def not_found(_e):
    return jsonify({"error": "endpoint not found"}), 404


@bp.app_errorhandler(405)
def method_not_allowed(_e):
    return jsonify({"error": "method not allowed"}), 405
