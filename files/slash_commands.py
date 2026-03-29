"""
JARVIS Slash Commands
---------------------
Pre-processes user messages before they reach the agent.
If a message starts with a slash command, it's expanded into a rich prompt
that the agent can handle with maximum context and structure.

Supported commands:
  /flashcards <topic>   — Anki-style Q&A cards (front/back)
  /feynman <topic>      — Feynman technique explanation
  /outline <topic>      — Hierarchical structured outline
  /quiz <topic>         — Multiple-choice quiz with answer key
  /help                 — List all slash commands
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedCommand:
    command: str          # e.g. "flashcards"
    topic: str            # everything after the command
    expanded_prompt: str  # what actually gets sent to the agent
    is_slash: bool = True


# ── Prompt templates ──────────────────────────────────────────────────────────

def _flashcards_prompt(topic: str) -> str:
    return f"""Generate Anki-style flashcards for: **{topic}**

Format each card exactly like this (repeat for 8–12 cards):

Q: [concise question]
A: [clear, complete answer]

---

Requirements:
- Cover the most important concepts, definitions, and relationships
- Questions should test understanding, not just recall
- Answers should be self-contained (readable without context)
- Mix conceptual, definitional, and application questions
- If the topic has formulae or code, include 1–2 cards on those
- At the end, add a section: ## Key Themes (3–5 bullet summary)

Search your knowledge base for any notes on {topic} and incorporate them.
"""


def _feynman_prompt(topic: str) -> str:
    return f"""Explain **{topic}** using the Feynman Technique.

Structure your explanation like this:

## The Core Idea (in one sentence)
[Simple, jargon-free summary]

## How It Actually Works
[Explain as if teaching a curious 16-year-old. No jargon without immediate definition.
Use concrete analogies and real-world examples.]

## A Concrete Example
[Walk through a specific, worked example step by step]

## Where People Get Confused
[Identify the 2–3 most common misconceptions or sticking points]

## How This Connects
[Link to 2–3 related concepts the learner probably already knows]

## Test Yourself
[3 questions that would confirm genuine understanding]

Search your knowledge base for any notes or prior context on {topic}.
"""


def _outline_prompt(topic: str) -> str:
    return f"""Create a comprehensive structured outline for: **{topic}**

Format:
# {topic}

## 1. [Major section]
   ### 1.1 [Subsection]
      - Key point
      - Key point
   ### 1.2 [Subsection]
      ...

## 2. [Major section]
   ...

Requirements:
- 4–6 major sections
- 2–4 subsections per major section
- Concrete bullet points (not vague placeholders)
- At the end: ## Prerequisites (what you need to know first)
- At the end: ## Recommended Resources (types of sources, not specific URLs unless you know them)

Search your knowledge base for any notes on {topic} to enrich the outline.
"""


def _quiz_prompt(topic: str) -> str:
    return f"""Create a multiple-choice quiz on: **{topic}**

Generate exactly 8 questions. Format:

**Q1.** [Question text]
A) [Option]
B) [Option]
C) [Option]
D) [Option]

[Repeat for Q2–Q8]

---
## Answer Key
Q1: [letter] — [brief explanation of why]
Q2: [letter] — [brief explanation]
...

Requirements:
- Mix difficulty: 2 easy, 4 medium, 2 hard
- Plausible distractors (wrong answers that look reasonable)
- Each explanation teaches something, not just "because it's correct"
- Cover different aspects: definitions, applications, comparisons, edge cases

Search your knowledge base for any notes on {topic}.
"""


# ── Command registry ──────────────────────────────────────────────────────────

_COMMANDS: dict[str, tuple[str, callable]] = {
    "flashcards": ("Generate Anki-style flashcards for a topic", _flashcards_prompt),
    "feynman":    ("Explain a topic using the Feynman technique", _feynman_prompt),
    "outline":    ("Create a hierarchical outline of a topic",    _outline_prompt),
    "quiz":       ("Generate a multiple-choice quiz",             _quiz_prompt),
}


def parse_slash_command(message: str) -> Optional[ParsedCommand]:
    """
    If message starts with a known slash command, return a ParsedCommand.
    Otherwise return None (message should be passed through unchanged).
    """
    message = message.strip()
    if not message.startswith("/"):
        return None

    # Extract command and topic
    parts = message[1:].split(None, 1)  # split on first whitespace
    cmd = parts[0].lower()
    topic = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "help":
        help_text = "**JARVIS Slash Commands**\n\n"
        for name, (desc, _) in _COMMANDS.items():
            help_text += f"  `/{name} <topic>` — {desc}\n"
        return ParsedCommand(
            command="help",
            topic="",
            expanded_prompt=help_text,
            is_slash=True,
        )

    if cmd not in _COMMANDS:
        # Unknown command — return it as-is for the agent to handle
        return None

    if not topic:
        return ParsedCommand(
            command=cmd,
            topic="",
            expanded_prompt=(
                f"The user typed `/{cmd}` but didn't specify a topic. "
                f"Ask them: 'What topic would you like me to create {cmd} for?'"
            ),
            is_slash=True,
        )

    _, prompt_fn = _COMMANDS[cmd]
    return ParsedCommand(
        command=cmd,
        topic=topic,
        expanded_prompt=prompt_fn(topic),
        is_slash=True,
    )


def process_message(message: str) -> tuple[str, Optional[ParsedCommand]]:
    """
    Main entry point.
    Returns (prompt_to_send, parsed_command_or_none).
    If no slash command, returns the original message.
    """
    parsed = parse_slash_command(message)
    if parsed:
        return parsed.expanded_prompt, parsed
    return message, None


def list_commands() -> list[dict]:
    """Return command metadata for the /help endpoint."""
    return [
        {"command": f"/{name}", "description": desc}
        for name, (desc, _) in _COMMANDS.items()
    ] + [{"command": "/help", "description": "List all slash commands"}]
