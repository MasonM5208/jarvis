"""
JARVIS Launch Script
--------------------
Starts everything in the right order:
  1. Ollama (if not already running)
  2. Ensures required models are pulled
  3. JARVIS API daemon
  4. Open WebUI (via Docker, or pip as fallback)
  5. Opens the dashboard in your browser

Run: python launch.py
     python launch.py --no-webui   (skip Open WebUI)
     python launch.py --no-browser (don't open browser)
"""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

JARVIS_DIR  = Path(__file__).resolve().parent
VENV_PYTHON = JARVIS_DIR.parent / ".venv" / "bin" / "python3"
PYTHON      = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

_no_webui   = "--no-webui"   in sys.argv
_no_browser = "--no-browser" in sys.argv


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


def _port_open(port: int) -> bool:
    return bool(_run(f"lsof -i :{port} -t").stdout.strip())


def _step(n: int, text: str):
    print(f"\n[{n}] {text}")


def _ok(msg: str):
    print(f"    ✅ {msg}")


def _err(msg: str):
    print(f"    ❌ {msg}")


def _info(msg: str):
    print(f"    ℹ️  {msg}")


# ── Step 1: Ollama ────────────────────────────────────────────────────────────

_step(1, "Checking Ollama...")

if _port_open(11434):
    _ok("Ollama already running on :11434")
else:
    _info("Starting Ollama...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    if _port_open(11434):
        _ok("Ollama started")
    else:
        _err("Could not start Ollama. Install with: brew install ollama")
        sys.exit(1)

# Pull required models if missing
_info("Checking models...")
models_out = _run("ollama list").stdout
for model in ["llama3.2", "nomic-embed-text"]:
    if model not in models_out:
        print(f"    Pulling {model} (first time only)...")
        subprocess.run(f"ollama pull {model}", shell=True)
        _ok(f"{model} ready")
    else:
        _ok(f"{model} already present")


# ── Step 2: JARVIS API ────────────────────────────────────────────────────────

_step(2, "Starting JARVIS API...")

if _port_open(8000):
    _ok("JARVIS API already running on :8000")
else:
    subprocess.Popen(
        [PYTHON, str(JARVIS_DIR / "daemon.py"), "start"],
        cwd=str(JARVIS_DIR),
    )
    print("    Waiting", end="", flush=True)
    for _ in range(20):
        time.sleep(1)
        print(".", end="", flush=True)
        if _port_open(8000):
            break
    print()
    if _port_open(8000):
        _ok("JARVIS API running on :8000")
    else:
        _err("JARVIS API failed to start — check: python daemon.py logs")
        sys.exit(1)


# ── Step 3: Open WebUI ────────────────────────────────────────────────────────

if not _no_webui:
    _step(3, "Checking Open WebUI...")

    if _port_open(3000):
        _ok("Open WebUI already running on :3000")

    else:
        docker_check = _run("docker info 2>/dev/null")
        docker_ps    = _run("docker ps -a 2>/dev/null").stdout

        if "open-webui" in docker_ps:
            _info("Starting existing Open WebUI container...")
            _run("docker start open-webui")
            time.sleep(3)
            _ok("Open WebUI started")

        elif docker_check.returncode == 0:
            _info("Creating Open WebUI container via Docker...")
            cmd = (
                "docker run -d --name open-webui -p 3000:3000 "
                "--add-host=host.docker.internal:host-gateway "
                "-e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 "
                "-e OPENAI_API_KEY=none "
                "-v open-webui:/app/backend/data "
                "ghcr.io/open-webui/open-webui:main"
            )
            result = _run(cmd)
            if result.returncode == 0:
                _ok("Open WebUI container started (first launch may take a minute)")
            else:
                _err(f"Docker error: {result.stderr[:150]}")
                _info("Falling back to pip install...")
                venv_pip = JARVIS_DIR.parent / ".venv" / "bin" / "pip"
                pip = str(venv_pip) if venv_pip.exists() else "pip3"
                subprocess.run(f"{pip} install open-webui -q", shell=True)
                subprocess.Popen(
                    "OPENAI_API_BASE_URL=http://localhost:8000/v1 "
                    "OPENAI_API_KEY=none open-webui serve",
                    shell=True, cwd=str(JARVIS_DIR),
                )
                time.sleep(4)
                _ok("Open WebUI started via pip")

        else:
            _info("Docker not found. Installing Open WebUI via pip...")
            venv_pip = JARVIS_DIR.parent / ".venv" / "bin" / "pip"
            pip = str(venv_pip) if venv_pip.exists() else "pip3"
            subprocess.run(f"{pip} install open-webui -q", shell=True)
            subprocess.Popen(
                "OPENAI_API_BASE_URL=http://localhost:8000/v1 "
                "OPENAI_API_KEY=none open-webui serve",
                shell=True, cwd=str(JARVIS_DIR),
            )
            time.sleep(4)
            _ok("Open WebUI started via pip")


# ── Done ──────────────────────────────────────────────────────────────────────

print("\n" + "━" * 52)
print("  ✅ JARVIS is fully online\n")
print(f"  🤖 JARVIS API  → http://localhost:8000")
print(f"  📊 Dashboard   → http://localhost:8000/ui/dashboard.html")
if not _no_webui:
    print(f"  🌐 Open WebUI  → http://localhost:3000")
print()
print("  In Open WebUI, select model 'llama3.2'")
print("  Try: /flashcards recursion  or  /feynman TCP/IP")
print("━" * 52 + "\n")

if not _no_browser:
    time.sleep(1)
    if not _no_webui:
        webbrowser.open("http://localhost:3000")
    else:
        webbrowser.open("http://localhost:8000/ui/dashboard.html")
