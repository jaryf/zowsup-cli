"""
Bearer-token authentication for the Dashboard API.

Configuration:
    Set DASHBOARD_API_TOKEN environment variable (e.g. in conf/config.conf or .env).
    If the variable is empty / unset → auth is BYPASSED (development mode only).
    Always set a strong random token in production.

Exempted endpoints:
    GET /api/health  — always public, used by monitoring probes.
    Test environments (TESTING or PYTEST_CURRENT_TEST) — bypass auth entirely.

Usage:
    # Blueprint-wide protection (preferred):
    @bp.before_request
    def _auth():
        return check_bearer()

    # Per-view (for fine-grained control):
    @bp.route("/protected")
    @require_auth
    def protected_view():
        ...
"""

import functools
import hmac
import logging
import os
import secrets
import time

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
_warned_no_token = False   # log the "no token" warning only once per process

# Phase 6: auth blueprint — exposes /api/auth/verify and /api/auth/refresh
auth_bp = Blueprint("auth", __name__)


def _expected_token() -> str:
    """Return the configured bearer token (empty string if not set)."""
    return os.environ.get("DASHBOARD_API_TOKEN", "").strip()


def _is_test_env() -> bool:
    return bool(os.environ.get("TESTING") or os.environ.get("PYTEST_CURRENT_TEST"))


def check_bearer():
    """
    Validate the Authorization: Bearer <token> header.

    Returns a (Response, status_code) tuple if the request should be rejected,
    or None if it is allowed.  Suitable for use in Flask before_request hooks.
    """
    global _warned_no_token

    if _is_test_env():
        return None

    expected = _expected_token()
    if not expected:
        if not _warned_no_token:
            logger.warning(
                "DASHBOARD_API_TOKEN is not set — API auth is DISABLED. "
                "Set the token in the environment before production use."
            )
            _warned_no_token = True
        try:
            from app.dashboard.utils.audit_log import log_auth_bypass
            log_auth_bypass()
        except Exception:
            pass
        return None

    auth_header = request.headers.get("Authorization", "")
    # EventSource (SSE) clients cannot set custom headers in browsers.
    # Accept the token as a ?token= query parameter as a fallback.
    if not auth_header.startswith("Bearer "):
        qs_token = request.args.get("token", "").strip()
        if qs_token:
            auth_header = f"Bearer {qs_token}"

    if not auth_header.startswith("Bearer "):
        try:
            from app.dashboard.utils.audit_log import log_auth_failure
            log_auth_failure("missing_header")
        except Exception:
            pass
        return (
            jsonify({"error": "Missing or malformed Authorization header"}),
            401,
        )

    provided = auth_header[len("Bearer "):].strip()
    try:
        valid = hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("utf-8")
        )
    except Exception:
        valid = False

    if not valid:
        logger.warning(
            "Dashboard API: invalid token from %s %s",
            request.remote_addr,
            request.path,
        )
        try:
            from app.dashboard.utils.audit_log import log_auth_failure
            log_auth_failure("invalid_token")
        except Exception:
            pass
        return jsonify({"error": "Invalid token"}), 401

    return None


def require_auth(f):
    """Decorator — apply bearer-token auth to a single view function."""

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        result = check_bearer()
        if result is not None:
            return result
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Phase 6 — 7.14  /api/auth/verify  &  /api/auth/refresh
# ---------------------------------------------------------------------------

@auth_bp.route("/verify", methods=["GET"])
def verify_token():
    """
    Verify that the current bearer token is valid.

    GET /api/auth/verify
    Authorization: Bearer <token>

    Returns 200 + {valid: true}  or  401 + {valid: false}.
    Used by the frontend to decide whether to redirect to a config page.
    Also recorded in the security audit log.
    """
    result = check_bearer()
    try:
        from app.dashboard.utils.audit_log import log_token_verify
        log_token_verify(result is None)
    except Exception:
        pass

    if result is not None:
        return jsonify({"valid": False, "error": "Invalid or missing token"}), 401

    expected = _expected_token()
    return jsonify({
        "valid": True,
        "auth_configured": bool(expected),
    }), 200


@auth_bp.route("/refresh", methods=["POST"])
def refresh_token():
    """
    Generate a rotation-ready replacement token.

    POST /api/auth/refresh
    Authorization: Bearer <current_token>

    This endpoint:
      1. Validates the current token.
      2. Generates a cryptographically random 32-byte hex token.
      3. Returns it as ``{new_token: "..."}`` — the operator must then
         restart the service with ``DASHBOARD_API_TOKEN=<new_token>``.

    The new token is NOT automatically applied; it is the operator's
    responsibility to update the environment variable and restart.

    Rationale: rotating tokens in a stateless env-var setup cannot be done
    without a restart.  This endpoint makes it easy to generate a strong new
    token without leaving the browser.
    """
    auth_result = check_bearer()
    if auth_result is not None:
        return auth_result

    new_token = secrets.token_hex(32)
    logger.info(
        "Token rotation requested by %s — restart with DASHBOARD_API_TOKEN=<new_token>",
        request.remote_addr,
    )
    return jsonify({
        "new_token": new_token,
        "instructions": (
            "Set DASHBOARD_API_TOKEN=<new_token> and restart script/dashboard.py "
            "to activate the new token."
        ),
    }), 200
