"""
Slash Command Handlers
-----------------------
Intercept /command messages before they reach the LLM.

Supported commands:
  /flashcards <topic>  — Anki-style Q&A cards
  /feynman <topic>     — Feynman technique explanation
  /outline <topic>     — structured study outline
  /quiz <topic>        — self-assessment quiz
  /ingest <path>       — ingest file/directory into memory
  /obsidian [path]     — sync Obsidian vault
  /plugin <request>    — request a new plugin be built
  /help                — list all commands
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from logger import get_logger

log = get_logger(__name__)


@dataclass
class CommandResult:
    prompt: str
    pre_response: str = ""
    bypass_llm: bool = False


def _get_context(memory, topic: str, n: int = 5) -> str:
    if not memory:
        return ""
    try:
        hits = memory.knowledge.search(topic, n=n)
        return "\n\n".join(h["text"] for h in hits if h["score"] > 0.35)
    except Exception:
        return ""


def _cmd_flashcards(topic: str, memory) -> CommandResult:
    ctx = _get_context(memory, topic)
    prompt = f"""Generate 10 Anki-style flashcards for: **{topic}**

{f"Source notes:{chr(10)}{chr(10)}{ctx}" if ctx else ""}

Format each card:
Q: [question]
A: [answer]

Number 1-10. After the cards, note which are highest priority."""
    return CommandResult(prompt=prompt, pre_response=f"📚 Generating flashcards for **{topic}**...")


def _cmd_feynman(topic: str, memory) -> CommandResult:
    ctx = _get_context(memory, topic)
    prompt = f"""Use the Feynman Technique to explain: **{topic}**

{f"Relevant notes:{chr(10)}{chr(10)}{ctx}" if ctx else ""}

Structure:
1. Simple explanation (teach a 12-year-old)
2. Core concept
3. Analogy
4. Common misconceptions
5. The actually hard part
6. One-sentence summary"""
    return CommandResult(prompt=prompt, pre_response=f"🧠 Feynman technique: **{topic}**...")


def _cmd_outline(topic: str, memory) -> CommandResult:
    ctx = _get_context(memory, topic)
    prompt = f"""Create a comprehensive study outline for: **{topic}**

{f"Based on these notes:{chr(10)}{chr(10)}{ctx}" if ctx else ""}

Use ## sections and ### subsections. Mark [FOUNDATIONAL], [INTERMEDIATE], [ADVANCED].
Include prerequisites, key concepts, formulas, applications, and likely exam questions."""
    return CommandResult(prompt=prompt, pre_response=f"📋 Building outline for **{topic}**...")


def _cmd_quiz(topic: str, memory) -> CommandResult:
    ctx = _get_context(memory, topic)
    prompt = f"""Create a 10-question quiz on: **{topic}**

{f"Based on these notes:{chr(10)}{chr(10)}{ctx}" if ctx else ""}

Include: 4 multiple choice, 3 true/false with explanation, 2 short answer, 1 problem-solving.
End with an Answer Key and scoring guide."""
    return CommandResult(prompt=prompt, pre_response=f"📝 Generating quiz on **{topic}**...")


def _cmd_ingest(path_str: str, memory) -> CommandResult:
    if not memory:
        return CommandResult(prompt="", pre_response="❌ Memory not available.", bypass_llm=True)
    from pathlib import Path
    path = Path(path_str.strip()).expanduser().resolve()
    if not path.exists():
        return CommandResult(prompt="", pre_response=f"❌ Path not found: `{path}`", bypass_llm=True)
    try:
        if path.is_dir():
            results = []
            for f in path.rglob("*"):
                if f.is_file() and f.suffix.lower() in {".txt", ".md", ".py", ".rst", ".csv", ".json", ".pdf"}:
                    try:
                        n = memory.ingest(str(f))
                        results.append(f"  ✅ {f.name} ({n} chunks)")
                    except Exception as e:
                        results.append(f"  ❌ {f.name}: {e}")
            return CommandResult(prompt="", pre_response=f"📚 Ingested `{path.name}/`\n" + "\n".join(results), bypass_llm=True)
        else:
            n = memory.ingest(str(path))
            return CommandResult(prompt="", pre_response=f"✅ Ingested `{path.name}` → {n} chunks", bypass_llm=True)
    except Exception as e:
        return CommandResult(prompt="", pre_response=f"❌ Ingest failed: {e}", bypass_llm=True)


def _cmd_obsidian(args: str, memory) -> CommandResult:
    if not memory:
        return CommandResult(prompt="", pre_response="❌ Memory not available.", bypass_llm=True)
    try:
        results = memory.ingest_obsidian(args.strip() or None)
        ok, errors = len(results["ok"]), len(results["errors"])
        lines = [f"🗂️  Obsidian sync: {ok} files ingested, {errors} errors"]
        for e in results["errors"][:5]:
            lines.append(f"  ❌ {e['file']}: {e['error']}")
        return CommandResult(prompt="", pre_response="\n".join(lines), bypass_llm=True)
    except Exception as e:
        return CommandResult(prompt="", pre_response=f"❌ Obsidian sync failed: {e}", bypass_llm=True)


def _cmd_plugin(args: str, memory) -> CommandResult:
    """Handle all /plugin subcommands: list, approve, reject, request."""
    args = args.strip()
    parts = args.split(None, 1)
    sub = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    # ── list ──────────────────────────────────────────────────────────────────
    if sub == "list":
        try:
            from tools.plugin_registry import PluginStore
            from config.settings import settings
            store = PluginStore(settings.sqlite_path.replace(".db", "_plugins.db"))
            loaded = [p["name"] for p in store.list_approved()]
            pending = [p["name"] for p in store.list_pending()]
            lines = ["**Plugin Status:**"]
            if loaded:
                lines.append(f"✅ Approved: {', '.join(loaded)}")
            if pending:
                lines.append(f"⏳ Pending review: {', '.join(pending)}")
            if not loaded and not pending:
                lines.append("No plugins yet.")
            return CommandResult(prompt="", bypass_llm=True, pre_response="\n".join(lines))
        except Exception as e:
            return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ Error: {e}")

    # ── approve ───────────────────────────────────────────────────────────────
    if sub == "approve" and arg:
        try:
            from tools.plugin_registry import PluginStore, load_plugin_from_file, PLUGINS_DIR
            from config.settings import settings
            from pathlib import Path
            store = PluginStore(settings.sqlite_path.replace(".db", "_plugins.db"))
            plugin = store.get(arg)
            if not plugin:
                return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ No plugin named `{arg}`.")
            filename = f"{arg}.py"
            filepath = PLUGINS_DIR / filename
            filepath.write_text(plugin["code"], encoding="utf-8")
            store.approve(arg, filename)
            return CommandResult(
                prompt="", bypass_llm=True,
                pre_response=f"✅ Plugin `{arg}` approved and saved to plugins/{filename}.\nRestart JARVIS to load it, or use the API /plugins endpoint to hot-load."
            )
        except Exception as e:
            return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ Approve failed: {e}")

    # ── reject ────────────────────────────────────────────────────────────────
    if sub == "reject" and arg:
        try:
            from tools.plugin_registry import PluginStore
            from config.settings import settings
            store = PluginStore(settings.sqlite_path.replace(".db", "_plugins.db"))
            store.reject(arg)
            return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ Plugin `{arg}` rejected.")
        except Exception as e:
            return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ Reject failed: {e}")

    # ── request ───────────────────────────────────────────────────────────────
    if sub == "request" and arg:
        try:
            from tools.plugin_registry import generate_plugin_code, PluginStore, PLUGINS_DIR
            from config.settings import settings
            if not settings.anthropic_api_key:
                return CommandResult(
                    prompt="", bypass_llm=True,
                    pre_response="❌ ANTHROPIC_API_KEY not set in .env — cannot generate plugin via Claude."
                )
            tool_name, code = generate_plugin_code(arg)
            store = PluginStore(settings.sqlite_path.replace(".db", "_plugins.db"))
            store.save(tool_name, arg, code)
            return CommandResult(
                prompt="", bypass_llm=True,
                pre_response=(
                    f"🔧 Plugin `{tool_name}` drafted via Claude.\n\n"
                    f"```python\n{code}\n```\n\n"
                    f"Review the code, then:\n"
                    f"  /plugin approve {tool_name}\n"
                    f"  /plugin reject {tool_name}"
                )
            )
        except Exception as e:
            return CommandResult(prompt="", bypass_llm=True, pre_response=f"❌ Plugin generation failed: {e}")

    # ── fallback ──────────────────────────────────────────────────────────────
    return CommandResult(prompt="", bypass_llm=True, pre_response=(
        "**Plugin commands:**\n"
        "  /plugin list\n"
        "  /plugin request <description>\n"
        "  /plugin approve <name>\n"
        "  /plugin reject <name>"
    ))



def _cmd_search(query: str, memory) -> CommandResult:
    if not query:
        return CommandResult(prompt="", pre_response="Usage: `/search <query>`", bypass_llm=True)
    if not memory:
        return CommandResult(prompt="", pre_response="❌ Memory not available.", bypass_llm=True)
    try:
        results = memory.search_conversations(query, n=5)
        if not results:
            return CommandResult(prompt="", pre_response=f"No past conversations found for: **{query}**", bypass_llm=True)
        lines = [f"🔍 Top {len(results)} matches for **{query}**:\n"]
        for i, r in enumerate(results, 1):
            ts = r["ingested_at"][:10] if r["ingested_at"] else "unknown date"
            preview = r["text"][:200].replace("\n", " ")
            lines.append(f"**{i}.** `{ts}` (score: {r['score']:.2f})\n> {preview}\n")
        return CommandResult(prompt="", pre_response="\n".join(lines), bypass_llm=True)
    except Exception as e:
        return CommandResult(prompt="", pre_response=f"❌ Search failed: {e}", bypass_llm=True)

def _cmd_help(_: str, __) -> CommandResult:
    return CommandResult(prompt="", bypass_llm=True, pre_response="""**JARVIS Slash Commands**

| Command | Description |
|---------|-------------|
| `/flashcards <topic>` | 10 Anki-style Q&A cards |
| `/feynman <topic>` | Feynman technique explanation |
| `/outline <topic>` | Hierarchical study outline |
| `/quiz <topic>` | 10-question self-assessment |
| `/ingest <path>` | Ingest a file or folder |
| `/obsidian [path]` | Sync Obsidian vault |
| `/search <query>` | Semantic search past conversations |
| `/plugin <request>` | Request a new capability |
| `/help` | Show this message |""")


_COMMANDS: dict[str, Callable] = {
    "flashcards": _cmd_flashcards,
    "feynman":    _cmd_feynman,
    "outline":    _cmd_outline,
    "quiz":       _cmd_quiz,
    "ingest":     _cmd_ingest,
    "obsidian":   _cmd_obsidian,
    "plugin":     _cmd_plugin,
    "search":     _cmd_search,
    "help":       _cmd_help,
}


def handle_slash_command(message: str, memory=None) -> CommandResult | None:
    """Process a message. Returns CommandResult if slash command, else None."""
    message = message.strip()
    if not message.startswith("/"):
        return None
    match = re.match(r"^/(\w+)(?:\s+(.*))?$", message, re.DOTALL)
    if not match:
        return None
    cmd = match.group(1).lower()
    args = (match.group(2) or "").strip()
    handler = _COMMANDS.get(cmd)
    if handler is None:
        return CommandResult(prompt="", pre_response=f"❓ Unknown command `/{cmd}`. Try `/help`.", bypass_llm=True)
    log.info("slash_command", command=cmd, args=args[:50] if args else "")
    try:
        return handler(args, memory)
    except Exception as e:
        log.error("slash_command_error", command=cmd, error=str(e))
        return CommandResult(prompt="", pre_response=f"❌ `/{cmd}` failed: {e}", bypass_llm=True)
