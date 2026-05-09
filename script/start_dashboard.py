#!/usr/bin/env python
"""
start_dashboard.py — Start the Dashboard backend and Vite frontend dev server together.

Usage
-----
    python script/start_dashboard.py              # both backend (Flask) + frontend (Vite dev)
    python script/start_dashboard.py --backend    # backend only  (same as: python script/dashboard_server.py)
    python script/start_dashboard.py --frontend   # frontend only (same as: cd app/dashboard/frontend && npm run dev)

Environment
-----------
All environment variables accepted by script/dashboard_server.py apply here too
(DASHBOARD_HOST, DASHBOARD_PORT, FLASK_DEBUG, …).

Individual startup is still fully supported:
    python script/dashboard_server.py            # backend alone
    cd app/dashboard/frontend ; npm run dev      # frontend alone
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "app" / "dashboard" / "frontend"


def _load_dotenv() -> None:
    """Load .env from the project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    except ImportError:
        pass


def _start_backend() -> "subprocess.Popen[bytes]":
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "script" / "dashboard_server.py")],
        cwd=str(PROJECT_ROOT),
    )


def _start_frontend() -> "subprocess.Popen[bytes]":
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(FRONTEND_DIR),
    )


def main() -> None:
    args = set(sys.argv[1:])
    _load_dotenv()

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"  # noqa: F841 (kept for clarity)

    procs: "list[tuple[str, subprocess.Popen]]" = []

    # --frontend flag means "frontend only" → skip backend
    if "--frontend" not in args:
        procs.append(("backend", _start_backend()))

    # --backend flag means "backend only" → skip frontend
    if "--backend" not in args:
        procs.append(("frontend", _start_frontend()))

    if not procs:
        # Should not happen given the logic above, but guard anyway.
        print("Nothing to start.", file=sys.stderr)
        sys.exit(1)

    def _stop_all(signum=None, frame=None) -> None:  # noqa: ANN001
        for _name, proc in procs:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

    signal.signal(signal.SIGINT, _stop_all)
    signal.signal(signal.SIGTERM, _stop_all)

    # Monitor: if any process exits unexpectedly, shut down the others.
    try:
        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[run_all] {name} exited with code {code}", flush=True)
                    _stop_all()
                    sys.exit(code)
            time.sleep(0.5)
    except KeyboardInterrupt:
        _stop_all()


if __name__ == "__main__":
    main()
