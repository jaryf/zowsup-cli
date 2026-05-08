"""
app/dashboard/utils/avatar_queue.py
─────────────────────────────────────
File-based IPC for avatar URL fetching.

The dashboard enqueues JIDs that need avatar URLs via `enqueue_avatar_request`.
The bot process (ZowBotLayer) reads the queue via `dequeue_avatar_requests`,
calls `contact.getavatar` for each JID, then persists the result via
`save_avatar_url`.  The dashboard reads cached URLs via `get_avatar_url`.

All file writes are atomic (tmp-file + rename) to avoid races between the
bot process and the Flask process.
"""

import json
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_QUEUE_FILE = Path("data") / "avatar_queue.json"
_UPDATES_FILE = Path("data") / "avatar_updates.json"

# Re-fetch avatar if cached URL is older than this many seconds (7 days)
_STALE_SECONDS = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Public API — dashboard side
# ---------------------------------------------------------------------------

def enqueue_avatar_request(jid: str) -> None:
    """Add *jid* to the avatar fetch queue.  Idempotent; no-op if already queued."""
    queue = _read_queue()
    if jid not in queue:
        queue.append(jid)
        _write_queue(queue)


def get_avatar_url(jid: str, db_path: str) -> Optional[str]:
    """Return the cached avatar URL for *jid*, or ``None`` if not available."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT avatar_url FROM user_profiles WHERE user_jid = ?", (jid,)
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def is_avatar_stale(jid: str, db_path: str) -> bool:
    """Return ``True`` if the avatar is missing or older than ``_STALE_SECONDS``."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT avatar_url, avatar_fetched_at FROM user_profiles WHERE user_jid = ?",
            (jid,),
        ).fetchone()
        if not row or not row[0]:
            return True
        fetched_at = row[1] or 0
        return (time.time() - fetched_at) > _STALE_SECONDS
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API — bot side
# ---------------------------------------------------------------------------

def dequeue_avatar_requests() -> List[str]:
    """
    Atomically read *and clear* the queue.

    Returns the list of JIDs that were pending.  The queue file is left
    empty (``[]``) after this call so the bot does not re-process the same
    JIDs on the next poll cycle.
    """
    queue = _read_queue()
    if queue:
        _write_queue([])
    return queue


def save_avatar_url(jid: str, url: str, db_path: str) -> None:
    """
    Persist *url* as the avatar for *jid* in the dashboard DB.

    Creates a minimal ``user_profiles`` row if none exists yet.
    """
    now = int(time.time())
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_jid, total_interactions) VALUES (?, 0)",
            (jid,),
        )
        conn.execute(
            "UPDATE user_profiles SET avatar_url = ?, avatar_fetched_at = ? WHERE user_jid = ?",
            (url, now, jid),
        )
        conn.commit()
    finally:
        conn.close()


def save_display_name(jid: str, name: str, db_path: str) -> None:
    """
    Persist *name* as the display name for *jid* in the dashboard DB.

    Creates a minimal ``user_profiles`` row if none exists yet.
    """
    if not name:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_jid, total_interactions) VALUES (?, 0)",
            (jid,),
        )
        conn.execute(
            "UPDATE user_profiles SET display_name = ? WHERE user_jid = ?",
            (name, jid),
        )
        conn.commit()
    finally:
        conn.close()


def save_group_members(
    group_jid: str,
    participants: dict,
    db_path: str,
    participant_lids: dict = None,
) -> None:
    """
    Persist the full member list returned by ``group.info`` into the
    ``group_members`` table.

    *participants* is the dict ``{jid: role}`` from
    ``InfoGroupsResultIqProtocolEntity.participants``.

    *participant_lids* is an optional ``{jid: lid}`` dict mapping each
    participant key to its LID address (e.g. ``xxx@lid``).  Stored in
    ``participant_lid`` so that incoming LID-addressed messages can be
    matched back to the correct row.

    Uses UPSERT: refreshes role / synced_at; never overwrites last_seen;
    updates participant_lid only when a new non-NULL value is provided.
    """
    if not participants:
        return
    now = int(time.time())
    lids = participant_lids or {}
    conn = sqlite3.connect(db_path)
    try:
        for participant_jid, role in participants.items():
            if not participant_jid:
                continue
            lid = lids.get(participant_jid) or None
            conn.execute(
                """
                INSERT INTO group_members (group_jid, participant_jid, role, synced_at, participant_lid)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_jid, participant_jid)
                DO UPDATE SET
                    role            = excluded.role,
                    synced_at       = excluded.synced_at,
                    participant_lid = COALESCE(excluded.participant_lid, participant_lid)
                """,
                (group_jid, participant_jid, role, now, lid),
            )
        conn.commit()
    finally:
        conn.close()


def notify_avatar_updated(jid: str, url: str) -> None:
    """
    Write a {jid, url} entry to ``data/avatar_updates.json`` so the Flask
    WebSocket monitor can push an ``avatar_updated`` SocketIO event to the
    frontend.  Idempotent — overwrites any existing pending update for the
    same JID.
    """
    try:
        updates = _read_updates()
        updates[jid] = url
        _write_updates(updates)
    except Exception as exc:
        logger.debug("notify_avatar_updated failed for %s: %s", jid, exc)


def pop_avatar_updates() -> dict:
    """
    Atomically read *and clear* the avatar updates file.

    Returns a dict mapping jid → url for all pending updates.
    Called by the Flask WebSocket monitor thread.
    """
    updates = _read_updates()
    if updates:
        _write_updates({})
    return updates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_queue() -> List[str]:
    """Read queue file; return empty list on any error."""
    try:
        with open(_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write_queue(queue: List[str]) -> None:
    """Atomically overwrite the queue file."""
    _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_QUEUE_FILE.parent, prefix=".avatar_queue_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(queue, f)
        os.replace(tmp, _QUEUE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_updates() -> dict:
    """Read avatar updates file; return empty dict on any error."""
    try:
        with open(_UPDATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_updates(updates: dict) -> None:
    """Atomically overwrite the avatar updates file."""
    _UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_UPDATES_FILE.parent, prefix=".avatar_updates_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(updates, f)
        os.replace(tmp, _UPDATES_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

