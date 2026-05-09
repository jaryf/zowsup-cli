"""
app/dashboard/utils/send_queue.py
──────────────────────────────────
File-based IPC for outgoing message sending.

The dashboard enqueues tasks via `enqueue_send_task`.
The bot process (ZowBotLayer) reads the queue via `dequeue_send_tasks`,
calls the appropriate command (msg.send / msg.sendmedia), and marks
tasks done by writing results to `send_results.json`.

All file writes are atomic (tmp-file + rename) to avoid races.
"""

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_QUEUE_FILE   = Path("data") / "send_queue.json"
_RESULTS_FILE = Path("data") / "send_results.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_json_atomic(path: Path, data: Any) -> None:
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API — dashboard side
# ---------------------------------------------------------------------------

def enqueue_send_task(
    to_jid: str,
    message_type: str,
    content: str,
    bot_jid: Optional[str] = None,
    media_url: Optional[str] = None,
    caption: Optional[str] = None,
) -> str:
    """
    Add a send task to the queue.  Returns the task ID.

    Args:
        to_jid:       Recipient JID (e.g. 8613800001234@s.whatsapp.net)
        message_type: "text" | "image" | "video" | "audio" | "document"
        content:      Text body (for text) or caption
        bot_jid:      Sending bot JID; None to let bot decide
        media_url:    URL or local path for media (required for non-text)
        caption:      Caption for media messages
    """
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "to_jid": to_jid,
        "message_type": message_type,
        "content": content,
        "bot_jid": bot_jid,
        "media_url": media_url,
        "caption": caption,
        "created_at": int(time.time()),
        "status": "pending",
    }
    queue: List[Dict] = _read_json(_QUEUE_FILE)
    if not isinstance(queue, list):
        queue = []
    queue.append(task)
    _write_json_atomic(_QUEUE_FILE, queue)
    logger.info("Enqueued send task %s to %s type=%s", task_id, to_jid, message_type)
    return task_id


def get_send_result(task_id: str) -> Optional[Dict]:
    """Return the result dict for a task, or None if not yet written."""
    results: List[Dict] = _read_json(_RESULTS_FILE)
    if not isinstance(results, list):
        return None
    for r in results:
        if isinstance(r, dict) and r.get("id") == task_id:
            return r
    return None


# ---------------------------------------------------------------------------
# Public API — bot side
# ---------------------------------------------------------------------------

def dequeue_send_tasks(bot_jid: Optional[str] = None) -> List[Dict]:
    """
    Atomically read and remove tasks destined for *bot_jid* from the queue.

    If *bot_jid* is None (or the task has no ``bot_jid``), the task is
    considered a wildcard and will be taken by the first bot that polls.
    Tasks destined for OTHER bots are left in the queue untouched.

    Returns the list of matched task dicts (may be empty).
    """
    queue: List[Dict] = _read_json(_QUEUE_FILE)
    if not isinstance(queue, list) or not queue:
        return []

    mine: List[Dict] = []
    remaining: List[Dict] = []
    for task in queue:
        if not isinstance(task, dict):
            continue
        task_bot = (task.get("bot_jid") or "").strip()
        if not task_bot or not bot_jid or task_bot == bot_jid:
            mine.append(task)
        else:
            remaining.append(task)

    if not mine:
        return []

    # Write back only the tasks that belong to other bots
    _write_json_atomic(_QUEUE_FILE, remaining)
    return mine


def write_send_result(task_id: str, success: bool, detail: str = "") -> None:
    """Record the outcome of a send task (called by bot after execution)."""
    results: List[Dict] = _read_json(_RESULTS_FILE)
    if not isinstance(results, list):
        results = []
    # Keep only the last 200 results to cap file size
    results = [r for r in results if isinstance(r, dict) and r.get("id") != task_id]
    results.append({
        "id": task_id,
        "success": success,
        "detail": detail,
        "done_at": int(time.time()),
    })
    results = results[-200:]
    _write_json_atomic(_RESULTS_FILE, results)
