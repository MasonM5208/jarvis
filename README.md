# JARVIS v2 — Personal AI Second Brain

Locally-hosted AI agent. Runs fully offline on your Mac,
deployable to Raspberry Pi 5 + AI HAT+ with no code changes.

**What's new in v2:**
- `/flashcards`, `/feynman`, `/outline`, `/quiz` slash commands
- PDF ingestion via PyMuPDF (lecture slides, textbooks)
- Obsidian vault sync
- Dynamic plugin registry — JARVIS writes its own tools, you approve them
- Structured JSON logging (structlog + rich)
- Clean `.env` config — no hardcoded paths or secrets
- Pinned `requirements.txt`
- Admin dashboard at `http://localhost:8000/ui/dashboard.html`

---

## Quick Start (Mac)

### 1. Install Ollama + models
```bash
brew install ollama
ollama serve
ollama pull llama3.2
ollama pull nomic-embed-text
```

### 2. Clone and set up Python environment
```bash
cd ~/Downloads/
python3 -m venv .venv
source .venv/bin/activate
cd jarvis/
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY for plugin generation
nano .env
```

### 4. Start JARVIS
```bash
python main.py
# API:       http://localhost:8000
# Dashboard: http://localhost:8000/ui/dashboard.html
```

### 5. Connect Open WebUI (optional but recommended)
```bash
docker run -d -p 3000:3000 \
  --add-host=host.docker.internal:host-gateway \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OPENAI_API_KEY=none \
  ghcr.io/open-webui/open-webui:main
# → http://localhost:3000
```

---

## Slash Commands

Type these in Open WebUI, the CLI, or anywhere that talks to the API.
JARVIS automatically uses your ingested notes as context.

| Command | What it does |
|---------|-------------|
| `/flashcards calculus` | 10 Anki-style Q&A cards, sourced from your notes |
| `/feynman recursion` | Feynman technique explanation of any concept |
| `/outline operating systems` | Hierarchical study outline with difficulty tags |
| `/quiz linear algebra` | 10-question self-assessment with answer key |
| `/ingest ~/Documents/CS101` | Ingest a folder of notes (txt/md/py/pdf) |
| `/ingest ~/lectures/week3.pdf` | Ingest a single PDF |
| `/obsidian` | Sync your entire Obsidian vault |
| `/plugin request <desc>` | Ask JARVIS to write a new tool for itself |
| `/plugin list` | See pending/approved plugins |
| `/plugin approve <name>` | Approve a generated plugin (loads at runtime) |
| `/plugin reject <name>` | Reject a generated plugin |
| `/help` | Show all commands |

---

## PDF Ingestion

JARVIS uses PyMuPDF for fast, accurate extraction:

```bash
# Via CLI
curl -X POST http://localhost:8000/ingest/path \
  -H "Content-Type: application/json" \
  -d '{"path": "~/Downloads/textbook.pdf"}'

# Via slash command (in chat)
/ingest ~/Downloads/lecture_slides.pdf

# Upload via dashboard
# → http://localhost:8000/ui/dashboard.html → Ingest tab
```

Handles: text PDFs, slide decks, mixed content, scanned pages (OCR fallback).

---

## Obsidian Sync

```bash
# Auto-detect vault from .env OBSIDIAN_VAULT_PATH
/obsidian

# Specify a vault path
/obsidian ~/Documents/MyVault

# Via API
curl -X POST http://localhost:8000/ingest/obsidian \
  -H "Content-Type: application/json" \
  -d '{"vault_path": "~/Documents/Obsidian"}'
```

---

## Dynamic Plugin System

When JARVIS hits a capability gap, it can write its own tools:

```
# In chat:
/plugin request I need a tool to fetch my university's exam schedule from their API

# JARVIS drafts the code and shows it to you
# Review the code, then:
/plugin approve fetch_exam_schedule

# The tool is saved to plugins/ and loaded immediately — no restart needed
```

Plugins are stored in `plugins/` and tracked in SQLite. You can also manage them
via the dashboard at `/ui/dashboard.html → Plugins`.

**Safety:** No code ever runs without your explicit approval.
You see the full function before it's saved.

---

## Configuration (.env)

Copy `.env.example` → `.env` and edit:

```bash
# Required for plugin generation
ANTHROPIC_API_KEY=sk-ant-...

# Platform (mac | pi | pc)
JARVIS_PLATFORM=mac

# Models
OLLAMA_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text

# Your Obsidian vault
OBSIDIAN_VAULT_PATH=~/Documents/Obsidian

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=console    # or "json" for production

# API security (optional, leave empty for local use)
JARVIS_API_TOKEN=
```

---

## Structured Logging

All logs are structured (machine-readable JSON in production,
rich colored output in development):

```bash
# Console mode (default, nice colors)
LOG_FORMAT=console python main.py

# JSON mode (production / log aggregation)
LOG_FORMAT=json python main.py

# Logs also written to
tail -f logs/jarvis.log
```

Each log event has: `timestamp`, `level`, `logger`, `event`, and typed key-value fields:
```json
{"event": "chat_request", "session_id": "abc123", "message_preview": "explain...", "level": "info"}
{"event": "pdf_ingested",  "path": "~/notes.pdf",  "chunks_stored": 47,            "level": "info"}
{"event": "plugin_approved","name": "fetch_grades", "file": "fetch_grades.py",      "level": "info"}
```

---

## Project Structure

```
jarvis/
├── main.py                    # FastAPI server — start here
├── logger.py                  # Structured logging (structlog)
├── requirements.txt           # Pinned dependencies
├── .env.example               # Config template — copy to .env
│
├── config/
│   └── settings.py            # Pydantic settings, loads .env
│
├── agent/
│   ├── agent.py               # LangGraph ReAct loop
│   └── slash_commands.py      # /flashcards /feynman /outline /quiz etc.
│
├── memory/
│   ├── memory_manager.py      # ChromaDB + SQLite + Obsidian sync
│   └── pdf_ingest.py          # PyMuPDF extraction pipeline
│
├── tools/
│   ├── tools.py               # All base agent tools
│   └── plugin_registry.py     # Dynamic plugin lifecycle
│
├── plugins/                   # Generated plugins live here (git-ignored)
│
├── interface/
│   └── dashboard.html         # Admin UI → localhost:8000/ui/dashboard.html
│
└── data/
    ├── chroma/                # Vector store (auto-created)
    ├── sqlite/                # Conversations + summaries + plugin metadata
    ├── uploads/               # Files uploaded via API
    └── logs/                  # Structured JSON logs
```

---

## Adding Tools Manually

```python
# tools/tools.py
@tool
def my_new_tool(param: Annotated[str, "What this param is"]) -> str:
    """Describe what this tool does — the agent reads this to decide when to call it."""
    return "result"

# Add to ALL_TOOLS at the bottom
ALL_TOOLS = [..., my_new_tool]
```

---

## Deploying to Raspberry Pi

1. Change one line in `.env`:
   ```
   JARVIS_PLATFORM=pi
   ```

2. Set up Hailo runtime:
   ```bash
   pip install hailo-platform
   # Download HEF model from Hailo Model Zoo
   ```

3. Everything else is identical — same commands, same API, same dashboard.

---

## Upgrading from v1

The main breaking changes:
- `config/settings.py` now loads from `.env` — copy `.env.example` to `.env`
- `requirements.txt` is now pinned — run `pip install -r requirements.txt` again
- `duckduckgo_search` renamed to `ddgs` — already handled in `tools.py`
- Logging now uses `structlog` — `from logger import get_logger` in your modules
- `datetime.utcnow()` replaced with `datetime.now(UTC)` everywhere
