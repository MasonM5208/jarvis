"""
JARVIS Daily Briefing
---------------------
Generates an on-demand morning briefing by pulling:
  - Current date/time
  - Long-term summaries (projects, goals) from SQLite
  - Recent knowledge chunks (past ~24h) from ChromaDB
  - Asks the LLM to synthesise a focused summary

Triggered by:
  - /brief slash command (CLI / Open WebUI)
  - Menu bar → "Daily Briefing"
  - POST /brief API endpoint
"""

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import JarvisAgent


BRIEFING_PROMPT = """
You are JARVIS, Mason's personal AI assistant.

Generate a focused, useful morning briefing. Be concise — aim for under 200 words.
Use this structure exactly:

1. **Today** — day, date, and one sentence about what matters today
2. **Projects** — active projects and their current status (from context below)
3. **Study focus** — what to prioritise studying today based on goals and notes
4. **Quick note** — one insight, reminder, or thing worth thinking about

Do not pad or repeat. Cut anything that isn't actionable.

Current date/time: {datetime}

{context}
"""


def generate_briefing(agent: "JarvisAgent") -> str:
    """
    Build and return a briefing string.
    Pulls memory context, calls the agent's LLM directly (no tool loop).
    """
    now = datetime.now().strftime("%A, %B %d %Y at %I:%M %p")

    # Pull long-term summaries
    summaries = agent.memory.episodic.get_summaries()
    summary_text = ""
    if summaries:
        lines = [f"[{s['category']}] {s['content']}" for s in summaries]
        summary_text = "## What I know about you\n" + "\n".join(lines)

    # Pull recent knowledge (last day — use a broad query)
    hits = agent.memory.knowledge.search("projects goals study notes", n=8)
    knowledge_text = ""
    if hits:
        relevant = [h for h in hits if h["score"] > 0.35][:5]
        if relevant:
            knowledge_text = "## Recent knowledge\n" + "\n\n".join(
                f"[from {h['source']}]\n{h['text'][:300]}" for h in relevant
            )

    context_parts = [p for p in [summary_text, knowledge_text] if p]
    context = "\n\n---\n\n".join(context_parts) if context_parts else "(no stored context yet)"

    prompt = BRIEFING_PROMPT.format(datetime=now, context=context)

    # Call LLM directly — no memory save, no tool loop
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="You are JARVIS, a concise personal AI assistant."),
            HumanMessage(content=prompt),
        ]
        result = agent.llm.invoke(messages)
        return result.content.strip()
    except Exception as e:
        return f"[Briefing error: {e}]"


def format_briefing_for_speech(briefing: str) -> str:
    """
    Strip markdown formatting so TTS reads cleanly.
    Bold markers, headers, bullet dashes → clean prose.
    """
    import re
    text = briefing
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)   # **bold** → plain
    text = re.sub(r"#{1,3}\s*", "", text)            # ## headers
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
