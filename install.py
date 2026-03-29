"""
JARVIS Installer
----------------
One-time setup. Run after creating your venv and installing requirements.txt.

What it does:
  1. Validates the .env file exists (copies .env.example if not)
  2. Installs hotkey / menu-bar dependencies
  3. Creates the LaunchAgent plist for auto-start on login
  4. Adds shell aliases to ~/.zshrc
  5. Opens Accessibility settings (required for global hotkey)

Run once:
    python install.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

JARVIS_DIR   = Path(__file__).resolve().parent
VENV_PYTHON  = JARVIS_DIR.parent / ".venv" / "bin" / "python3"
VENV_PIP     = JARVIS_DIR.parent / ".venv" / "bin" / "pip3"
PYTHON       = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
PIP          = str(VENV_PIP)    if VENV_PIP.exists()    else "pip3"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PLIST_DEST    = LAUNCH_AGENTS / "com.jarvis.agent.plist"


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def _step(n: int, title: str):
    print(f"\n{'━'*50}")
    print(f"  Step {n}: {title}")
    print(f"{'━'*50}")


# ── Step 1: .env file ─────────────────────────────────────────────────────────
_step(1, "Checking .env configuration")

env_file     = JARVIS_DIR / ".env"
env_example  = JARVIS_DIR / ".env.example"

if env_file.exists():
    print("  ✅ .env already exists")
else:
    if env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        print(f"  ✅ Created .env from .env.example")
        print(f"  ⚠️  Edit {env_file} and add your ANTHROPIC_API_KEY")
    else:
        print(f"  ❌ .env.example not found — create .env manually")

# Warn if ANTHROPIC_API_KEY is empty
content = env_file.read_text() if env_file.exists() else ""
if "ANTHROPIC_API_KEY=sk-ant" not in content:
    print("  ⚠️  ANTHROPIC_API_KEY not set in .env — plugin generation will be disabled")
    print("     Get a key at: https://console.anthropic.com/")


# ── Step 2: Hotkey dependencies ───────────────────────────────────────────────
_step(2, "Installing hotkey & menu-bar dependencies")

packages = ["rumps", "pyobjc-framework-Cocoa", "pyobjc-framework-AppKit", "httpx"]
for pkg in packages:
    print(f"  Installing {pkg}...", end="", flush=True)
    result = _run(f"{PIP} install {pkg} -q")
    print(" ✅" if result.returncode == 0 else f" ❌  {result.stderr[:80]}")


# ── Step 3: LaunchAgent (auto-start) ─────────────────────────────────────────
_step(3, "Setting up auto-start on login (LaunchAgent)")

plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.agent</string>

    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{JARVIS_DIR}/daemon.py</string>
        <string>start</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{JARVIS_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{JARVIS_DIR}/data/logs/launchagent.log</string>

    <key>StandardErrorPath</key>
    <string>{JARVIS_DIR}/data/logs/launchagent.log</string>
</dict>
</plist>
"""

LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
PLIST_DEST.write_text(plist_content)

_run(f"launchctl unload {PLIST_DEST} 2>/dev/null")
result = _run(f"launchctl load {PLIST_DEST}")
if result.returncode == 0:
    print(f"  ✅ JARVIS will auto-start on login")
    print(f"     Plist: {PLIST_DEST}")
else:
    print(f"  ⚠️  launchctl load returned: {result.stderr.strip()}")
    print(f"     You can still start manually: python daemon.py start")


# ── Step 4: Accessibility permission ─────────────────────────────────────────
_step(4, "Accessibility permission (required for global hotkey)")
print("""
  The Cmd+Shift+J hotkey needs Accessibility access.

  To grant it:
  1. Open System Settings → Privacy & Security → Accessibility
  2. Click + and add your Terminal app (or iTerm2)
  3. Also add Python if prompted

  Opening settings now...
""")
_run("open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'")


# ── Step 5: Shell aliases ─────────────────────────────────────────────────────
_step(5, "Adding shell aliases to ~/.zshrc")

aliases = [
    f'\nalias jarvis="cd {JARVIS_DIR} && {PYTHON} cli.py"',
    f'alias jarvis-start="cd {JARVIS_DIR} && {PYTHON} daemon.py start"',
    f'alias jarvis-stop="cd {JARVIS_DIR} && {PYTHON} daemon.py stop"',
    f'alias jarvis-logs="cd {JARVIS_DIR} && {PYTHON} daemon.py logs"',
    f'alias jarvis-launch="cd {JARVIS_DIR} && {PYTHON} launch.py"',
]

shell_rc = Path.home() / ".zshrc"
existing = shell_rc.read_text() if shell_rc.exists() else ""

if "alias jarvis=" not in existing:
    with open(shell_rc, "a") as f:
        f.write("\n# JARVIS aliases\n")
        f.write("\n".join(aliases) + "\n")
    print(f"  ✅ Aliases added to {shell_rc}")
    print(f"     Run: source ~/.zshrc")
else:
    print(f"  ✅ Aliases already in {shell_rc}")

print("""
  Available after sourcing:
    jarvis         → open JARVIS CLI
    jarvis-start   → start background daemon
    jarvis-stop    → stop daemon
    jarvis-logs    → tail live logs
    jarvis-launch  → start everything + open WebUI
""")


# ── Done ──────────────────────────────────────────────────────────────────────
print("\n" + "━" * 50)
print("  ✅ Installation complete!\n")
print("  Next steps:")
print("  1. Edit .env — add ANTHROPIC_API_KEY")
print("  2. source ~/.zshrc")
print("  3. jarvis-launch      (start full stack)")
print("  4. python hotkey.py   (start menu bar + hotkey)")
print("━" * 50 + "\n")
