"""
JARVIS Daemon
-------------
Manages the JARVIS API server as a background process.

Commands:
    python daemon.py start    — start JARVIS in the background
    python daemon.py stop     — stop the running daemon
    python daemon.py restart  — stop then start
    python daemon.py status   — check if running
    python daemon.py logs     — tail the log file (Ctrl+C to exit)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
JARVIS_DIR  = Path(__file__).resolve().parent
DATA_DIR    = JARVIS_DIR / "data"
PID_FILE    = DATA_DIR / "jarvis.pid"
LOG_FILE    = DATA_DIR / "logs" / "jarvis.log"
VENV_PYTHON = JARVIS_DIR.parent / ".venv" / "bin" / "python3"
PYTHON      = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _pid() -> int | None:
    """Return the current daemon PID, or None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)   # signal 0 = existence check
        return pid
    except (ValueError, ProcessLookupError):
        PID_FILE.unlink(missing_ok=True)
        return None


def start():
    pid = _pid()
    if pid:
        print(f"✅ JARVIS already running (PID {pid})")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(LOG_FILE, "a") as log:
        proc = subprocess.Popen(
            [PYTHON, str(JARVIS_DIR / "main.py")],
            cwd=str(JARVIS_DIR),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    PID_FILE.write_text(str(proc.pid))
    print(f"🚀 JARVIS started (PID {proc.pid})")
    print(f"   Logs:      {LOG_FILE}")
    print(f"   API:       http://localhost:8000")
    print(f"   Dashboard: http://localhost:8000/ui/dashboard.html")


def stop():
    pid = _pid()
    if not pid:
        print("JARVIS is not running.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 5 seconds for graceful shutdown
        for _ in range(10):
            time.sleep(0.5)
            if _pid() is None:
                break
        PID_FILE.unlink(missing_ok=True)
        print(f"👋 JARVIS stopped (PID {pid})")
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        print("JARVIS was not running (stale PID removed).")


def restart():
    stop()
    time.sleep(1)
    start()


def status():
    pid = _pid()
    if pid:
        print(f"✅ JARVIS is running (PID {pid})")
        print(f"   API:       http://localhost:8000/health")
        print(f"   Dashboard: http://localhost:8000/ui/dashboard.html")
    else:
        print("⭕ JARVIS is not running.")
        print(f"   Start with: python daemon.py start")


def logs():
    if not LOG_FILE.exists():
        print(f"No log file found at {LOG_FILE}")
        print("Start JARVIS first: python daemon.py start")
        return
    print(f"Tailing {LOG_FILE}  (Ctrl+C to exit)\n{'─'*60}")
    try:
        subprocess.run(["tail", "-f", str(LOG_FILE)])
    except KeyboardInterrupt:
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

_COMMANDS = {
    "start": start,
    "stop": stop,
    "restart": restart,
    "status": status,
    "logs": logs,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    fn = _COMMANDS.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Usage: python daemon.py [{' | '.join(_COMMANDS)}]")
        sys.exit(1)
