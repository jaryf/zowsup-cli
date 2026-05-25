"""Dashboard server entry-point.

Run as a completely separate process from the bot:
    python script/dashboard_server.py

Environment variables (all optional):
    DASHBOARD_HOST       bind address  (default: 0.0.0.0)
    DASHBOARD_PORT       port          (default: 5000)
    DASHBOARD_DEBUG      enable debug  (default: false)
    DASHBOARD_API_TOKEN  bearer token  (default: empty = no auth, Phase 5 enforces)

IMPORTANT: This file MUST NOT import anything from the bot's asyncio stack
(zowbot_layer, consonance, core, etc.).  The two processes share ONLY the
dashboard.db file on disk.
"""

import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so `app.dashboard.*` resolves
# regardless of the working directory the user starts from.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Load .env file (if present) BEFORE reading any env vars.
# The file is optional — production deployments may prefer injecting
# environment variables directly via the process supervisor / container.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    _env_file = PROJECT_ROOT / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)  # don't override vars already set
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables

# ---------------------------------------------------------------------------
# Logging setup (before importing anything that logs)
# ---------------------------------------------------------------------------
_log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
if os.environ.get("DASHBOARD_DEBUG", "").lower() == "true":
    _log_level = logging.DEBUG
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard")

# ---------------------------------------------------------------------------
# Add rotating file handler (writes to logs/dashboard.log)
# ---------------------------------------------------------------------------
try:
    from app.dashboard.utils.logging_setup import setup_dashboard_logging
    setup_dashboard_logging()
except Exception:
    pass  # logging to file is best-effort; never crash at startup

# ---------------------------------------------------------------------------
# Mark this process as running in dashboard mode so config.py can gate
# DASHBOARD_DB_PATH (and other dashboard-only defaults) on this flag.
# Must be set before importing config.
# ---------------------------------------------------------------------------
os.environ.setdefault("DASHBOARD_MODE", "1")

# ---------------------------------------------------------------------------
# Import app factory (deferred so logging is set up first)
# ---------------------------------------------------------------------------
from app.dashboard.api.app import create_app
from app.dashboard.config import CONFIG

app = create_app()


if __name__ == "__main__":
    host = CONFIG["FLASK_HOST"]
    port = CONFIG["FLASK_PORT"]
    debug = CONFIG["FLASK_DEBUG"]

    logger.info(f"Starting Dashboard server on http://{host}:{port}  debug={debug}")
    logger.info(f"Dashboard DB: {CONFIG['DASHBOARD_DB_PATH']}")

    # ---------------------------------------------------------------------------
    # Print all registered routes
    # ---------------------------------------------------------------------------
    rules = sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule))
    logger.info(f"Registered routes ({len(rules)}):")
    max_rule = max((len(str(r.rule)) for r in rules), default=0)
    max_endpoint = max((len(r.endpoint) for r in rules), default=0)
    for rule in rules:
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"}) if rule.methods else []
        methods_str = ",".join(methods) if methods else "-"
        logger.info(
            f"  {methods_str:<20}  {str(rule.rule):<{max_rule}}  -> {rule.endpoint:<{max_endpoint}}"
        )

    # Use socketio.run() when Flask-SocketIO is active (supports WS upgrades).
    # Falls back to standard app.run() when SocketIO is not configured.
    sio = app.extensions.get("socketio")
    if sio is not None:
        logger.info("WebSocket support enabled (async_mode=threading)")
        sio.run(app, host=host, port=port, debug=debug, use_reloader=debug,
                allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=debug, use_reloader=debug)
