"""
JARVIS CLI
----------
Minimal terminal interface — no Docker, no WebUI required.

Usage:
    python cli.py

Commands while running:
    /flashcards <topic>   generate flashcards
    /feynman <topic>      Feynman technique explanation
    /outline <topic>      study outline
    /quiz <topic>         self-assessment quiz
    /ingest <path>        ingest a file or folder
    /obsidian             sync Obsidian vault
    /plugin list          list plugins
    ingest <path>         alias for /ingest
    stats                 show memory statistics
    new                   start a fresh session
    exit / quit           exit
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure jarvis/ is on the path when run directly
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from logger import init_logging
init_logging()

from agent.agent import JarvisAgent
from config.settings import settings


# ── Colours (no dependencies) ─────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"

def _c(text: str, *codes: str) -> str:
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + _RESET


# ── Main REPL ─────────────────────────────────────────────────────────────────

def main():
    print()
    print(_c(f"  {'━'*44}", _BOLD))
    print(_c(f"   {settings.agent_name}  —  Personal AI Agent  v2", _BOLD, _CYAN))
    print(_c(f"  {'━'*44}", _BOLD))
    print(_c("   Type /help for slash commands", _DIM))
    print(_c("   Type 'stats', 'new', or 'exit'", _DIM))
    print()

    agent = JarvisAgent()
    session_id = str(uuid.uuid4())

    while True:
        try:
            raw = input(_c("You: ", _BOLD, _YELLOW)).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n" + _c("Goodbye.", _DIM))
            break

        if not raw:
            continue

        low = raw.lower()

        # ── Built-in CLI commands ──────────────────────────────────────────────
        if low in ("exit", "quit"):
            print(_c("Goodbye.", _DIM))
            break

        if low == "stats":
            stats = agent.stats()
            mem = stats
            plugin_info = stats.get("plugins", {})
            print(_c(
                f"\n  📊 Knowledge chunks : {mem['knowledge_chunks']}\n"
                f"     Long-term facts  : {mem['summaries']}\n"
                f"     Loaded plugins   : {len(plugin_info.get('loaded', []))}\n"
                f"     Pending review   : {len(plugin_info.get('pending', []))}\n",
                _DIM,
            ))
            continue

        if low == "new":
            session_id = str(uuid.uuid4())
            print(_c("\n  🔄 New session started.\n", _DIM))
            continue

        # ── Legacy ingest shortcut (kept for muscle-memory) ────────────────────
        if low.startswith("ingest "):
            raw = "/" + raw   # rewrite to slash command

        # ── Forward to agent (handles all /commands + normal chat) ─────────────
        print(_c(f"\n{settings.agent_name}: ", _BOLD, _GREEN), end="", flush=True)
        try:
            response = agent.chat(raw, session_id=session_id)
        except KeyboardInterrupt:
            print(_c("\n  [interrupted]", _DIM))
            continue

        print(response)
        print()


if __name__ == "__main__":
    main()
