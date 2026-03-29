"""
JARVIS Hotkey & Menu Bar (macOS)
---------------------------------
Puts a 🤖 icon in the menu bar and registers a global hotkey (Cmd+Shift+J).
Pressing the hotkey shows a native macOS input dialog;
the response appears in a second dialog with a Copy button.

Requirements:
    pip install rumps pyobjc-framework-Cocoa pyobjc-framework-AppKit httpx

Run:
    python hotkey.py

Accessibility permission:
    System Settings → Privacy & Security → Accessibility → add Terminal (or Python)
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import httpx
import rumps

# ── Config ────────────────────────────────────────────────────────────────────
JARVIS_URL  = "http://localhost:8000/v1/chat/completions"
SESSION_ID  = "hotkey-session"   # persistent session across hotkey invocations
MODEL       = "llama3.2"


# ── API call ──────────────────────────────────────────────────────────────────

def ask_jarvis(message: str) -> str:
    try:
        r = httpx.post(
            JARVIS_URL,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": message}],
                "session_id": SESSION_ID,
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except httpx.ConnectError:
        return "❌ JARVIS is not running.\nStart it: python daemon.py start"
    except Exception as e:
        return f"❌ Error: {e}"


# ── Native macOS dialogs ──────────────────────────────────────────────────────

def _osa(script: str) -> str:
    """Run an AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def show_input_dialog() -> str | None:
    """Show a native input dialog. Returns text or None if cancelled."""
    result = _osa(
        'set r to text returned of '
        '(display dialog "Ask JARVIS:" default answer "" '
        'with title "JARVIS" buttons {"Cancel","Ask"} default button "Ask" with icon note)\n'
        'return r'
    )
    return result if result else None


def show_response_dialog(question: str, response: str):
    """Show response with a Copy button."""
    safe_resp = response.replace('"', '\\"').replace("\n", "\\n")
    safe_q    = question.replace('"', '\\"')[:50]
    script = (
        f'set btn to button returned of '
        f'(display dialog "{safe_resp}" '
        f'with title "JARVIS — {safe_q}…" '
        f'buttons {{"Copy","Done"}} default button "Done")\n'
        f'if btn is "Copy" then set the clipboard to "{safe_resp}"'
    )
    subprocess.Popen(["osascript", "-e", script])


def _notify(title: str, message: str):
    _osa(f'display notification "{message}" with title "{title}"')


# ── Query flow ────────────────────────────────────────────────────────────────

def handle_query():
    question = show_input_dialog()
    if not question:
        return
    threading.Thread(target=lambda: _notify("JARVIS", "Thinking…"), daemon=True).start()
    response = ask_jarvis(question)
    show_response_dialog(question, response)


# ── Global hotkey (Cmd+Shift+J) ───────────────────────────────────────────────

def register_hotkey():
    """Register Cmd+Shift+J system-wide via PyObjC."""
    try:
        import AppKit
        from Cocoa import NSKeyDown, NSCommandKeyMask, NSShiftKeyMask

        def handler(event):
            flags = event.modifierFlags()
            chars = event.charactersIgnoringModifiers()
            if chars == "j" and (flags & NSCommandKeyMask) and (flags & NSShiftKeyMask):
                threading.Thread(target=handle_query, daemon=True).start()

        AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSKeyDown, handler)
        print("⌨️  Hotkey registered: Cmd+Shift+J")
    except Exception as e:
        print(f"⚠️  Could not register hotkey: {e}")
        print("   Grant Accessibility in System Settings → Privacy & Security → Accessibility")


# ── Menu bar app ──────────────────────────────────────────────────────────────

class JarvisMenuBar(rumps.App):
    def __init__(self):
        super().__init__("JARVIS", "🤖")
        self.menu = [
            rumps.MenuItem("Ask JARVIS  ⌘⇧J", callback=self.ask),
            rumps.MenuItem("Check Status", callback=self.status),
            None,
            rumps.MenuItem("Start Daemon", callback=self.start_daemon),
            rumps.MenuItem("Stop Daemon", callback=self.stop_daemon),
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
        ]

    @rumps.clicked("Ask JARVIS  ⌘⇧J")
    def ask(self, _):
        threading.Thread(target=handle_query, daemon=True).start()

    @rumps.clicked("Check Status")
    def status(self, _):
        try:
            r = httpx.get("http://localhost:8000/health", timeout=3)
            d = r.json()
            s = d.get("stats", {})
            p = s.get("plugins", {})
            rumps.alert(
                "JARVIS Status",
                f"✅ Online\n"
                f"Model: {d.get('model', '?')}\n"
                f"Platform: {d.get('platform', '?')}\n"
                f"Knowledge chunks: {s.get('knowledge_chunks', 0)}\n"
                f"Summaries: {s.get('summaries', 0)}\n"
                f"Plugins loaded: {len(p.get('loaded', []))}",
            )
        except Exception:
            rumps.alert("JARVIS Status", "⭕ Offline\n\nStart with:\npython daemon.py start")

    @rumps.clicked("Start Daemon")
    def start_daemon(self, _):
        _daemon = Path(__file__).parent / "daemon.py"
        subprocess.Popen([sys.executable, str(_daemon), "start"])
        rumps.notification("JARVIS", "Starting…", "Ready in a few seconds.")

    @rumps.clicked("Stop Daemon")
    def stop_daemon(self, _):
        _daemon = Path(__file__).parent / "daemon.py"
        subprocess.run([sys.executable, str(_daemon), "stop"])
        rumps.notification("JARVIS", "Stopped", "Daemon has been shut down.")

    @rumps.clicked("Open Dashboard")
    def open_dashboard(self, _):
        subprocess.Popen(["open", "http://localhost:8000/ui/dashboard.html"])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🤖 JARVIS menu bar starting…")
    print("   Hotkey: Cmd+Shift+J")
    print("   Or click 🤖 in the menu bar")
    print("   Requires: pip install rumps pyobjc-framework-Cocoa pyobjc-framework-AppKit")
    register_hotkey()
    JarvisMenuBar().run()
