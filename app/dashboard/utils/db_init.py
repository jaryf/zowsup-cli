"""
Dashboard database initialisation.

Creates all tables in data/dashboard.db and configures WAL journal mode
so that the bot process (writer) and Flask process (reader) can operate
concurrently without hitting "database is locked" errors.

Tables created:
  - chat_messages       individual messages (both directions)
  - ai_thoughts         structured AI reasoning records (written in Phase 2)
  - user_profiles       computed user portraits       (written in Phase 2)
  - strategy_applications  strategy change history    (written in Phase 3)
  - strategy_conflicts  conflict detection records    (written in Phase 3)
  - daily_statistics    time-series snapshots         (written in Phase 2)

Usage:
    python -m app.dashboard.utils.db_init          # creates / migrates DB
    from app.dashboard.utils.db_init import init_db, get_db_connection
"""

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

from app.dashboard.config import CONFIG

logger = logging.getLogger(__name__)

DB_PATH: str = CONFIG["DASHBOARD_DB_PATH"]

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_jid         TEXT    NOT NULL,
    direction        TEXT    NOT NULL CHECK(direction IN ('in', 'out')),
    content          TEXT    NOT NULL,
    message_type     TEXT    NOT NULL DEFAULT 'text',
    timestamp        INTEGER NOT NULL,          -- Unix epoch seconds
    source_memory_id INTEGER,                   -- links to ai_memory.id during migration
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_AI_THOUGHTS = """
CREATE TABLE IF NOT EXISTS ai_thoughts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_jid                TEXT    NOT NULL,
    message_id              INTEGER,            -- FK → chat_messages.id (outgoing msg)
    intent                  TEXT,
    confidence              REAL,
    detected_keywords       TEXT,               -- JSON array
    strategy_selected       TEXT,
    strategy_reasoning      TEXT,
    tone                    TEXT,
    response_quality_score  REAL,
    raw_thought             TEXT,               -- full reasoning text if available
    urgency_level           TEXT,               -- 'high' / 'medium' / 'low' (Phase 3)
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_USER_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_jid             TEXT PRIMARY KEY,
    total_interactions   INTEGER NOT NULL DEFAULT 0,
    first_seen           TIMESTAMP,
    last_seen            TIMESTAMP,
    user_category        TEXT,                  -- VIP / regular / new / at_risk
    communication_style  TEXT,                  -- detailed / concise / impatient / patient
    topic_preferences    TEXT,                  -- JSON object {topic: count}
    satisfaction_score   REAL,
    trend_7d             TEXT,                  -- JSON {dates:[], counts:[]}
    trend_30d            TEXT,                  -- JSON {dates:[], counts:[]}
    current_strategy     TEXT,                  -- JSON snapshot of active strategy
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_STRATEGY_APPLICATIONS = """
CREATE TABLE IF NOT EXISTS strategy_applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_jid       TEXT,                         -- NULL means global strategy
    strategy_type  TEXT    NOT NULL,             -- 'global' | 'personal'
    config_json    TEXT    NOT NULL,             -- full strategy config as JSON
    version        INTEGER NOT NULL DEFAULT 1,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    applied_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    note           TEXT
);
"""

_DDL_STRATEGY_CONFLICTS = """
CREATE TABLE IF NOT EXISTS strategy_conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_jid        TEXT    NOT NULL,
    message_id      INTEGER,                     -- FK → chat_messages.id
    conflict_type   TEXT    NOT NULL,
    description     TEXT,
    resolved        INTEGER NOT NULL DEFAULT 0 CHECK(resolved IN (0,1)),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_DAILY_STATISTICS = """
CREATE TABLE IF NOT EXISTS daily_statistics (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    date                 TEXT    NOT NULL UNIQUE, -- YYYY-MM-DD
    total_messages       INTEGER NOT NULL DEFAULT 0,
    incoming_messages    INTEGER NOT NULL DEFAULT 0,
    outgoing_messages    INTEGER NOT NULL DEFAULT 0,
    total_active_users   INTEGER NOT NULL DEFAULT 0,
    new_users            INTEGER NOT NULL DEFAULT 0,
    ai_responses         INTEGER NOT NULL DEFAULT 0,
    avg_response_quality REAL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_GROUP_MEMBERS = """
CREATE TABLE IF NOT EXISTS group_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_jid       TEXT    NOT NULL,
    participant_jid TEXT    NOT NULL,
    role            TEXT,                          -- 'admin' | NULL (regular member)
    synced_at       INTEGER NOT NULL,              -- Unix epoch seconds
    last_seen       INTEGER,                       -- Unix epoch of last observed message
    participant_lid TEXT,                          -- LID address (xxx@lid) for LID-mode groups
    UNIQUE(group_jid, participant_jid)
);
"""

_DDL_MATERIALS = """
CREATE TABLE IF NOT EXISTS materials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL CHECK(type IN ('image', 'text', 'document', 'video', 'audio')),
    content     TEXT,                              -- text content or base64/URL for AI-generated images
    file_path   TEXT,                             -- relative path under data/materials/
    mime_type   TEXT,
    tags        TEXT,                             -- JSON array of tag strings
    ai_prompt   TEXT,                             -- prompt used to generate (if AI-generated)
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_MESSAGE_TEMPLATES = """
CREATE TABLE IF NOT EXISTS message_templates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    type         TEXT    NOT NULL CHECK(type IN ('text', 'image', 'document', 'location', 'buttons', 'list')),
    content_json TEXT    NOT NULL,                -- JSON describing the WhatsApp message structure
    description  TEXT,
    tags         TEXT,                           -- JSON array
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Indexes DDL
# ---------------------------------------------------------------------------

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_messages_user     ON chat_messages(user_jid)",
    "CREATE INDEX IF NOT EXISTS idx_messages_ts       ON chat_messages(timestamp)",
    # Phase 6: composite index for paginated per-user message queries
    "CREATE INDEX IF NOT EXISTS idx_messages_user_ts  ON chat_messages(user_jid, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_thoughts_user     ON ai_thoughts(user_jid)",
    "CREATE INDEX IF NOT EXISTS idx_thoughts_msg      ON ai_thoughts(message_id)",
    # Phase 6: composite index for per-user thoughts ordered by time
    "CREATE INDEX IF NOT EXISTS idx_thoughts_user_ts  ON ai_thoughts(user_jid, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_user     ON strategy_applications(user_jid)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_active   ON strategy_applications(is_active)",
    # Phase 6: composite for fetching the active strategy for a given user
    "CREATE INDEX IF NOT EXISTS idx_strategy_user_active ON strategy_applications(user_jid, is_active, applied_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_conflicts_user    ON strategy_conflicts(user_jid)",
    # Phase 6: composite for unresolved conflicts per user
    "CREATE INDEX IF NOT EXISTS idx_conflicts_user_resolved ON strategy_conflicts(user_jid, resolved)",
    "CREATE INDEX IF NOT EXISTS idx_daily_date        ON daily_statistics(date)",
]

_ALL_DDL = [
    _DDL_CHAT_MESSAGES,
    _DDL_AI_THOUGHTS,
    _DDL_USER_PROFILES,
    _DDL_STRATEGY_APPLICATIONS,
    _DDL_STRATEGY_CONFLICTS,
    _DDL_DAILY_STATISTICS,
    _DDL_GROUP_MEMBERS,
    _DDL_MATERIALS,
    _DDL_MESSAGE_TEMPLATES,
] + _INDEXES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _migrate_ai_thoughts_urgency(conn) -> None:
    """Add urgency_level column to ai_thoughts if it doesn't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(ai_thoughts)").fetchall()}
    if "urgency_level" not in existing:
        conn.execute("ALTER TABLE ai_thoughts ADD COLUMN urgency_level TEXT")


def _migrate_bot_jid(conn) -> None:
    """Add bot_jid column to chat_messages and ai_thoughts (idempotent)."""
    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "bot_jid" not in msg_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN bot_jid TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_bot ON chat_messages(bot_jid)"
        )

    thought_cols = {row[1] for row in conn.execute("PRAGMA table_info(ai_thoughts)").fetchall()}
    if "bot_jid" not in thought_cols:
        conn.execute("ALTER TABLE ai_thoughts ADD COLUMN bot_jid TEXT")


def _migrate_profile_overrides(conn) -> None:
    """Add manual-override, avatar and display_name columns to user_profiles if they don't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    if "user_category_override" not in existing:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN user_category_override TEXT")
    if "communication_style_override" not in existing:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN communication_style_override TEXT")
    if "avatar_url" not in existing:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN avatar_url TEXT")
    if "avatar_fetched_at" not in existing:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN avatar_fetched_at INTEGER")
    if "display_name" not in existing:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN display_name TEXT")


def _migrate_participant(conn) -> None:
    """Add participant and media_path columns to chat_messages if they don't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "participant" not in existing:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN participant TEXT")
    if "media_path" not in existing:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN media_path TEXT")


def _migrate_notify(conn) -> None:
    """Add notify column to chat_messages if it doesn't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "notify" not in existing:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN notify TEXT")


def _migrate_group_members_index(conn) -> None:
    """Add index on group_members(group_jid) if it doesn't exist (idempotent)."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_group_members_gid ON group_members(group_jid)"
    )


def _migrate_group_members_last_seen(conn) -> None:
    """Add last_seen column to group_members if it doesn't exist (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(group_members)").fetchall()}
    if "last_seen" not in existing:
        conn.execute("ALTER TABLE group_members ADD COLUMN last_seen INTEGER")
        logger.info("Migrated group_members: added last_seen column")


def _migrate_group_members_participant_lid(conn) -> None:
    """Add participant_lid column + index to group_members if missing (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(group_members)").fetchall()}
    if "participant_lid" not in existing:
        conn.execute("ALTER TABLE group_members ADD COLUMN participant_lid TEXT")
        logger.info("Migrated group_members: added participant_lid column")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_group_members_lid ON group_members(participant_lid)"
    )


def _migrate_translated_content(conn) -> None:
    """Add translated_content column to chat_messages if missing (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "translated_content" not in existing:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN translated_content TEXT")
        logger.info("Migrated chat_messages: added translated_content column")


def _migrate_message_source(conn) -> None:
    """Add source column to chat_messages if missing (idempotent).

    Values: NULL / 'ai' = generated by AI bot; 'manual' = sent by human operator
    via the dashboard composer.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "source" not in existing:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN source TEXT")
        logger.info("Migrated chat_messages: added source column")


def init_db(db_path: str = DB_PATH) -> None:
    """
    Create tables, indexes, and enable WAL mode.

    Safe to call multiple times (all DDL uses IF NOT EXISTS).
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        # WAL mode: allows concurrent readers while one writer is active.
        # Must be set before creating tables for the setting to persist.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        cursor = conn.cursor()
        for ddl in _ALL_DDL:
            cursor.execute(ddl)

        _migrate_ai_thoughts_urgency(conn)
        _migrate_bot_jid(conn)
        _migrate_profile_overrides(conn)
        _migrate_participant(conn)
        _migrate_notify(conn)
        _migrate_group_members_index(conn)
        _migrate_group_members_last_seen(conn)
        _migrate_group_members_participant_lid(conn)
        _migrate_translated_content(conn)
        _migrate_message_source(conn)
        conn.commit()
        logger.info(f"Dashboard DB initialised at {db_path} (WAL mode)")
    except Exception:
        conn.rollback()
        logger.exception("Failed to initialise dashboard DB")
        raise
    finally:
        conn.close()


@contextmanager
def get_db_connection(db_path: str = DB_PATH):
    """
    Context manager that yields a SQLite connection.

    Each call opens a new connection.  SQLite in WAL mode handles
    concurrent reads from multiple Flask worker threads safely.
    The caller must NOT share the returned connection across threads.

    Example::

        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM chat_messages").fetchall()
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Phase 6 — let SQLite update query-planner statistics periodically
    conn.execute("PRAGMA optimize=0x10002")
    try:
        yield conn
    finally:
        conn.close()


def verify_db(db_path: str = DB_PATH) -> dict:
    """
    Return a dict with table names and row counts.  Used by health endpoint.
    """
    expected_tables = [
        "chat_messages",
        "ai_thoughts",
        "user_profiles",
        "strategy_applications",
        "strategy_conflicts",
        "daily_statistics",
    ]
    result: dict = {"journal_mode": None, "tables": {}}

    with get_db_connection(db_path) as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        result["journal_mode"] = row[0] if row else "unknown"

        for tbl in expected_tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                result["tables"][tbl] = count
            except sqlite3.OperationalError:
                result["tables"][tbl] = "MISSING"

    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_db()
    info = verify_db()
    print(f"journal_mode = {info['journal_mode']}")
    for tbl, cnt in info["tables"].items():
        print(f"  {tbl}: {cnt} rows")
