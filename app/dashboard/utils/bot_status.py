"""
app/dashboard/utils/bot_status.py
──────────────────────────────────
Multi-account bot status management.

Each bot writes its own status file at data/bot_status_<phone>.json.
The legacy single-file path data/bot_status.json is kept for backward
compatibility (processes that don't pass a phone fall back to it).

Public API
----------
read_status(phone=None)     → dict        # single bot (legacy or by phone)
write_status(running, jid, pid, phone)    # single bot
clear_status(phone=None)                  # single bot
read_all_statuses()         → list[dict]  # all known bots
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

_DATA_DIR = Path("data")
_LEGACY_STATUS_FILE = _DATA_DIR / "bot_status.json"

_EMPTY: dict = {
    "running": False,
    "jid": None,
    "pid": None,
    "phone": None,
    "started_at": None,
    "updated_at": None,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _status_path(phone: Optional[str]) -> Path:
    """Return the status file path for a given phone (or legacy path if None)."""
    if phone:
        return _DATA_DIR / f"bot_status_{phone}.json"
    return _LEGACY_STATUS_FILE


def _read_status_file(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("running") and data.get("pid"):
            if not _pid_alive(data["pid"]):
                data["running"] = False
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_EMPTY)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_status(phone: Optional[str] = None) -> dict:
    """Return current bot status dict for the given phone; never raises."""
    return _read_status_file(_status_path(phone))


def write_status(
    running: bool,
    jid: Optional[str] = None,
    pid: Optional[int] = None,
    phone: Optional[str] = None,
) -> None:
    """Atomically write bot status."""
    path = _status_path(phone)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_status_file(path)
    payload = {
        "running": running,
        "jid": jid,
        "phone": phone,
        "pid": pid if pid is not None else os.getpid(),
        "started_at": existing.get("started_at") if running else None,
        "updated_at": time.time(),
    }
    if running and payload["started_at"] is None:
        payload["started_at"] = time.time()

    _atomic_write(path, json.dumps(payload, indent=2))


def clear_status(phone: Optional[str] = None) -> None:
    """Mark a bot as offline."""
    write_status(running=False, jid=None, phone=phone)


def read_all_statuses() -> list:
    """
    Return a list of status dicts for every known bot.

    Scans data/bot_status_*.json plus the legacy data/bot_status.json.
    Only returns entries where running=True or the file exists.
    """
    paths: list[Path] = list(_DATA_DIR.glob("bot_status_*.json"))
    if _LEGACY_STATUS_FILE.exists():
        paths.append(_LEGACY_STATUS_FILE)

    results = []
    seen_phones: set = set()
    for p in paths:
        entry = _read_status_file(p)
        phone_key = entry.get("phone") or entry.get("jid") or str(p)
        if phone_key in seen_phones:
            continue
        seen_phones.add(phone_key)
        results.append(entry)

    # Sort: running bots first, then by started_at descending
    results.sort(key=lambda e: (not e.get("running", False), -(e.get("started_at") or 0)))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    dir_ = path.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".bot_status_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)  # atomic on POSIX; near-atomic on Windows
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* is running (cross-platform safe)."""
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
