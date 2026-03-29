#!/usr/bin/env python3
"""
JARVIS Hotkey + Menu Bar
------------------------
Menu bar app with:
  - Cmd+Shift+J global hotkey
  - Native dialog with "Ask" (text) and "🎤 Speak" (voice) buttons
  - TTS toggle (persists in menu state)
  - Daily briefing trigger
  - Daemon start/stop

Requirements:
    pip install rumps pyobjc-framework-Cocoa pyobjc-framework-AppKit httpx
    pip install pyaudio faster-whisper  (for voice)
"""

import threading
import subprocess
import httpx
import rumps
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── Config ────────────────────────────────────────────────────────────────────
JARVIS_URL  = "http://localhost:8000/v1/chat/completions"
BRIEF_URL   = "http://localhost:8000/brief"
APP_NAME    = "JARVIS"
SESSION_ID  = "hotkey-session"

# Runtime TTS state — shared with voice module
_tts_enabled = True


# ── JARVIS API ────────────────────────────────────────────────────────────────

def ask_jarvis(message: str) -> str:
    try:
        r = httpx.post(
            JARVIS_URL,
            json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": message}],
                "session_id": SESSION_ID,
            },
            timeout=90,
        )
        return r.json()["choices"][0]["message"]["content"]
    except httpx.ConnectError:
        return "❌ JARVIS is not running. Start it with: python3 daemon.py start"
    except Exception as e:
        return f"❌ Error: {e}"


def get_briefing() -> str:
    try:
        r = httpx.post(BRIEF_URL, timeout=90)
        return r.json().get("briefing", "No briefing returned.")
    except httpx.ConnectError:
        return "❌ JARVIS is not running."
    except Exception as e:
        return f"❌ Briefing error: {e}"


# ── Dialog helpers (AppleScript) ──────────────────────────────────────────────

def _run_applescript(script: str) -> tuple[int, str]:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip()


def show_main_dialog() -> dict:
    """
    Show the main JARVIS dialog.
    Returns {'action': 'text'|'voice'|'brief'|'cancel', 'text': str}
    """
    script = '''
    tell application "System Events" to activate
    set dlg to display dialog "Ask JARVIS:" default answer "" ¬
        with title "JARVIS" ¬
        buttons {"🎤 Speak", "📋 Brief", "Ask"} ¬
        default button "Ask" ¬
        with icon note
    set btn to button returned of dlg
    set txt to text returned of dlg
    return btn & "|" & txt
    '''
    rc, out = _run_applescript(script)
    if rc != 0:
        return {"action": "cancel", "text": ""}

    parts = out.split("|", 1)
    btn   = parts[0].strip()
    text  = parts[1].strip() if len(parts) > 1 else ""

    if btn == "🎤 Speak":
        return {"action": "voice", "text": text}
    elif btn == "📋 Brief":
        return {"action": "brief", "text": ""}
    else:
        return {"action": "text", "text": text}


def show_response_dialog(title: str, response: str):
    """Show response with Copy button."""
    safe = response.replace('"', '\\"').replace('\n', '\\n')[:2000]
    short_title = title[:50].replace('"', '\\"')
    script = f'''
    set btn to button returned of (display dialog "{safe}" ¬
        with title "JARVIS — {short_title}" ¬
        buttons {{"Copy", "Done"}} default button "Done")
    if btn is "Copy" then
        set the clipboard to "{safe}"
    end if
    '''
    _run_applescript(script)


def notify(title: str, msg: str):
    script = f'display notification "{msg}" with title "{title}"'
    subprocess.Popen(["osascript", "-e", script])


# ── Voice flow ────────────────────────────────────────────────────────────────

def handle_voice() -> str | None:
    """Record mic, transcribe, return text. Returns None on failure."""
    try:
        from voice import get_voice
        v = get_voice(tts_enabled=_tts_enabled)
        notify("JARVIS", "Listening...")
        text = v.listen()
        if not text:
            notify("JARVIS", "Didn't catch that — try again")
        return text
    except Exception as e:
        notify("JARVIS", f"Voice error: {e}")
        return None


def speak_response(text: str):
    """Speak text if TTS is enabled."""
    if not _tts_enabled:
        return
    try:
        from voice import get_voice
        v = get_voice(tts_enabled=True)
        v.speak(text)
    except Exception:
        pass   # TTS failure is silent — user still sees the dialog


# ── Main query flow ───────────────────────────────────────────────────────────

def handle_query():
    """Full flow: show dialog → text or voice → send → respond."""
    result = show_main_dialog()
    action = result["action"]

    if action == "cancel":
        return

    if action == "brief":
        notify("JARVIS", "Generating briefing...")
        briefing = get_briefing()
        show_response_dialog("Daily Briefing", briefing)
        speak_response(briefing)
        return

    if action == "voice":
        question = handle_voice()
        if not question:
            return
    else:
        question = result["text"]
        if not question:
            return

    notify("JARVIS", "Thinking...")
    response = ask_jarvis(question)
    show_response_dialog(question, response)
    speak_response(response)


# ── Menu bar app ──────────────────────────────────────────────────────────────

class JarvisMenuBar(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME, "🤖")
        self._tts_item = rumps.MenuItem(
            "🔊 Voice responses: ON",
            callback=self.toggle_tts
        )
        self.menu = [
            rumps.MenuItem("Ask JARVIS  (Cmd+Shift+J)", callback=self.ask),
            rumps.MenuItem("🎤 Speak to JARVIS", callback=self.ask_voice),
            rumps.MenuItem("📋 Daily Briefing", callback=self.brief),
            None,
            self._tts_item,
            rumps.MenuItem("Check Status", callback=self.status),
            None,
            rumps.MenuItem("Start Daemon", callback=self.start_daemon),
            rumps.MenuItem("Stop Daemon", callback=self.stop_daemon),
        ]

    @rumps.clicked("Ask JARVIS  (Cmd+Shift+J)")
    def ask(self, _):
        threading.Thread(target=handle_query, daemon=True).start()

    @rumps.clicked("🎤 Speak to JARVIS")
    def ask_voice(self, _):
        def voice_flow():
            question = handle_voice()
            if not question:
                return
            notify("JARVIS", "Thinking...")
            response = ask_jarvis(question)
            show_response_dialog(question, response)
            speak_response(response)
        threading.Thread(target=voice_flow, daemon=True).start()

    @rumps.clicked("📋 Daily Briefing")
    def brief(self, _):
        def brief_flow():
            notify("JARVIS", "Generating briefing...")
            briefing = get_briefing()
            show_response_dialog("Daily Briefing", briefing)
            speak_response(briefing)
        threading.Thread(target=brief_flow, daemon=True).start()

    def toggle_tts(self, sender):
        global _tts_enabled
        _tts_enabled = not _tts_enabled
        label = "🔊 Voice responses: ON" if _tts_enabled else "🔇 Voice responses: OFF"
        sender.title = label
        # Sync with voice module instance if loaded
        try:
            from voice import _default_voice
            if _default_voice:
                _default_voice.set_tts(_tts_enabled)
        except Exception:
            pass

    @rumps.clicked("Check Status")
    def status(self, _):
        try:
            r = httpx.get("http://localhost:8000/health", timeout=3)
            data  = r.json()
            stats = data.get("stats", {})
            tts   = "ON" if _tts_enabled else "OFF"
            rumps.alert(
                "JARVIS Status",
                f"✅ Online\nModel: llama3.2\n"
                f"Knowledge chunks: {stats.get('knowledge_chunks', 0)}\n"
                f"Summaries: {stats.get('summaries', 0)}\n"
                f"Voice responses: {tts}"
            )
        except Exception:
            rumps.alert("JARVIS Status", "⭕ Offline — start daemon first")

    @rumps.clicked("Start Daemon")
    def start_daemon(self, _):
        daemon = Path(__file__).parent / "daemon.py"
        subprocess.Popen([sys.executable, str(daemon), "start"])
        rumps.notification("JARVIS", "Starting...", "API will be ready in a few seconds.")

    @rumps.clicked("Stop Daemon")
    def stop_daemon(self, _):
        daemon = Path(__file__).parent / "daemon.py"
        subprocess.run([sys.executable, str(daemon), "stop"])
        rumps.notification("JARVIS", "Stopped", "Daemon has been stopped.")


# ── Global hotkey ─────────────────────────────────────────────────────────────

def register_hotkey():
    try:
        import AppKit
        from AppKit import NSEvent
        from Cocoa import NSKeyDown, NSCommandKeyMask, NSShiftKeyMask

        def handler(event):
            flags = event.modifierFlags()
            chars = event.charactersIgnoringModifiers()
            if chars == "j" and (flags & NSCommandKeyMask) and (flags & NSShiftKeyMask):
                threading.Thread(target=handle_query, daemon=True).start()

        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSKeyDown, handler)
        print("⌨️  Hotkey registered: Cmd+Shift+J")
    except Exception as e:
        print(f"⚠️  Could not register global hotkey: {e}")
        print("    Grant Accessibility in System Settings → Privacy → Accessibility")


# ── Entry point ───────────────────────────────────────────────────────────────

class JarvisApp(JarvisMenuBar):
    @rumps.timer(1)
    def _register_hotkey_once(self, sender):
        sender.stop()
        register_hotkey()

if __name__ == "__main__":
    print("🤖 JARVIS menu bar starting...")
    print("   Hotkey: Cmd+Shift+J")
    print("   Or click 🤖 in your menu bar")
    JarvisApp().run()
