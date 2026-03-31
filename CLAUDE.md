# CLAUDE.md — JARVIS Codebase Guide

This file provides essential context for AI assistants working on the JARVIS codebase.

---

## Project Overview

JARVIS is a personal AI assistant with a three-tier memory system, dynamic plugin support, and a multi-platform deployment strategy. It exposes an OpenAI-compatible FastAPI server so any OpenAI-compatible client (e.g., Open WebUI) connects out of the box.

**Core capabilities:**
- LangGraph ReAct agent with dual LLM strategy (local chat + Claude for reliable tool calling)
- Three-tier memory: episodic (SQLite), semantic (ChromaDB), and summary tracking
- Dynamic plugin system — the agent can draft new tools at runtime, pending human approval
- Slash command interception before hitting the LLM
- PDF/document ingestion into the vector knowledge base
- Voice I/O (faster-whisper STT, AVSpeechSynthesizer TTS)
- macOS menu bar app with global hotkey (Cmd+Shift+J)
- Daily briefing generation
- Web clipper for saving URLs to memory

---

## Repository Structure

```
jarvis/
├── main.py               # FastAPI server (http://localhost:8000) — primary entry point
├── cli.py                # Terminal REPL interface
├── launch.py             # One-click launcher: Ollama → JARVIS → Open WebUI → browser
├── daemon.py             # Background daemon control (start/stop/status)
├── install.py            # Dependency installation helper
├── voice.py              # STT (faster-whisper) + TTS (AVSpeechSynthesizer)
├── hotkey.py             # macOS menu bar app + global hotkey
├── clipper.py            # Fetch URL → extract text → ingest into memory
├── briefing.py           # Daily briefing synthesis
├── logger.py             # Structured logging (structlog + rich + JSON)
│
├── config/
│   └── settings.py       # Platform-aware config; exports `settings` object + module-level constants
│
├── agent/
│   ├── agent.py          # JarvisAgent class — LangGraph ReAct orchestration
│   └── slash_commands.py # Slash command handlers (/flashcards, /feynman, /outline, /quiz, etc.)
│
├── memory/
│   ├── memory_manager.py # Memory class: episodic SQLite + semantic ChromaDB + summaries
│   └── pdf_ingest.py     # PDF extraction pipeline (pymupdf4llm + OCR fallback)
│
├── tools/
│   ├── tools.py          # Base tools list: file I/O, shell_execute, web_search, etc.
│   └── plugin_registry.py# Dynamic plugin lifecycle: draft → pending → approve/reject → hot-load
│
├── ga/
│   └── logger.py         # Analytics/feedback logging to SQLite
│
├── interface/
│   ├── dashboard.html    # Admin UI served at /ui/dashboard.html
│   └── chat.html         # Chat interface
│
├── plugins/
│   └── get_current_weather.py  # Example plugin (National Weather Service)
│
├── benchmarks/
│   ├── runner.py         # Benchmark execution engine
│   ├── suite.py          # BenchmarkCase definitions
│   └── scheduler.py      # Scheduled benchmark runs
│
└── data/                 # Runtime data (gitignored)
    ├── chroma/           # ChromaDB vector store
    ├── sqlite/jarvis.db  # SQLite: conversations, summaries, analytics, plugins
    ├── uploads/          # Uploaded files
    └── logs/             # JSON logs
```

---

## Entry Points

| Command | Purpose |
|---------|---------|
| `python main.py` | Start the FastAPI server on port 8000 |
| `python cli.py` | Interactive terminal chat (no web server) |
| `python launch.py` | Start everything: Ollama + JARVIS + Open WebUI + open browser |
| `python daemon.py start\|stop\|status` | Run JARVIS as a background daemon |
| `python install.py` | Install/configure dependencies |
| `python hotkey.py` | macOS menu bar app with Cmd+Shift+J hotkey |

---

## Platform Configuration

Platform resolution order (first match wins):

1. `local_settings.py` (gitignored, machine-local) — set `PLATFORM = "mac"` here
2. `JARVIS_PLATFORM` environment variable (in `.env` or systemd `EnvironmentFile`)
3. Default: `"mac"`

**Platform profiles** (`config/settings.py`):

| Platform | Backend | Model | Embedding |
|----------|---------|-------|-----------|
| `mac` | Ollama | `llama3.2` | `nomic-embed-text` |
| `pc` | Ollama | `llama3.1:8b` | `nomic-embed-text` |
| `pi` | llama_cpp (Hailo) | `llama3.2-3b` | `all-MiniLM-L6-v2` |

To override for your machine without affecting git, create `local_settings.py` in the project root:
```python
PLATFORM = "mac"  # or "pc" or "pi"
```

**Key environment variables** (copy `.env.example` to `.env`):
```
ANTHROPIC_API_KEY=sk-ant-...   # Required for tool-calling LLM + plugin generation
JARVIS_PLATFORM=mac            # Override platform
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

---

## Architecture: Dual LLM Strategy

The agent uses two LLMs with distinct roles:

- **`self.llm`** — local model (Ollama/llama.cpp). Used for direct chat and slash command responses. Fast, free, offline.
- **`self.tool_llm`** — `claude-haiku-4-5-20251001` via Anthropic API. Used by the LangGraph ReAct graph when tools are available. Dramatically more reliable at structured tool calling than small local models. Falls back to the local model if `ANTHROPIC_API_KEY` is not set.

This is intentional: do not collapse these into a single LLM.

---

## Request Flow

```
User message
    │
    ├─ Slash command? (/flashcards, /feynman, /brief, /stats, etc.)
    │       └─ handle_slash_command() → _llm_direct() (local LLM, no tools)
    │
    ├─ Plugin meta-command? (/plugin approve|reject|list|request|code)
    │       └─ _handle_plugin_meta() → returns immediately
    │
    └─ Normal chat
            ├─ memory.recall() — inject relevant context
            ├─ episodic history (last 10 messages)
            └─ LangGraph graph.invoke() (tool_llm + tools)
                    └─ memory.remember() — store exchange
```

---

## Memory System

Three tiers in `memory/memory_manager.py`:

| Tier | Storage | Purpose |
|------|---------|---------|
| Episodic | SQLite | Full conversation history per session_id |
| Semantic | ChromaDB | Chunked vector index for knowledge retrieval |
| Summary | SQLite | Long-term facts stored via `remember_fact` tool |

Key methods:
- `memory.recall(message, session_id)` — hybrid search, returns context string
- `memory.remember(session_id, role, content)` — append to episodic history
- `memory.learn(category, fact)` — store long-term fact
- `memory.ingest(path)` — chunk and index a file into ChromaDB
- `memory.stats()` — returns `{"knowledge_chunks": N, "summaries": N}`

**Memory context injection**: Context is prepended to the user message (not as a separate system message) because Claude's API rejects multiple system messages.

---

## Tools System

Base tools are defined in `tools/tools.py` and exported as `ALL_TOOLS`. Key tools:

- `read_file(path)` — read a local file
- `write_file(path, content)` — write to a local file
- `shell_execute(command)` — run shell commands (whitelist enforced by `ALLOWED_SHELL_COMMANDS`)
- `web_search(query)` — DuckDuckGo search via `ddgs`
- `remember_fact(category, fact)` — store long-term memory
- `ingest_document(path)` — ingest file into knowledge base

The `_bind_memory_tools()` function in `agent.py` replaces the stub versions of `remember_fact` and `ingest_document` with memory-wired live versions at agent init time.

**Shell safety**: `shell_execute` enforces `ALLOWED_SHELL_COMMANDS` from `config/settings.py`. Do not expand this whitelist without review.

---

## Plugin System

Dynamic plugins allow the agent (or user) to request new tools at runtime:

1. **Request**: `/plugin request <description>` — Claude generates Python code for a new tool
2. **Review**: `/plugin code <name>` — inspect the generated code
3. **Approve**: `/plugin approve <name>` — saves to `plugins/`, hot-loads, rebuilds LangGraph
4. **Reject**: `/plugin reject <name>` — discards
5. **List**: `/plugin list` — show loaded and pending plugins

Plugin files live in `plugins/`. Each must define a function decorated with `@tool` from `langchain_core.tools`. The `PluginRegistry` in `tools/plugin_registry.py` manages the lifecycle. `ANTHROPIC_API_KEY` is required for plugin generation.

---

## API Endpoints

The FastAPI server (`main.py`) exposes:

**OpenAI-compatible:**
- `GET /v1/models` — list available models
- `POST /v1/chat/completions` — chat (streaming supported)

**JARVIS-specific:**
- `GET /health` — server status + memory stats
- `POST /brief` — generate daily briefing (`{"speak": true}` for TTS)
- `POST /ingest/path` — ingest file/folder by path `{"path": "..."}`
- `POST /ingest/upload` — upload and ingest a file
- `GET /memory/stats` — memory statistics
- `GET /memory/summaries` — long-term summaries
- `POST /feedback` — thumbs up/down `{"session_id": "...", "positive": true}`
- `GET /ga/logs?limit=50` — recent analytics logs
- `POST /tts/toggle?enabled=true` — toggle TTS
- `POST /clip` — web clipper `{"url": "...", "tags": ["..."]}`

**Static UI:** `http://localhost:8000/ui/dashboard.html` and `/ui/chat.html`

---

## Slash Commands

Slash commands are intercepted before the LLM in `agent/slash_commands.py` and `main.py`. They use the local LLM directly (no tools):

| Command | Description |
|---------|-------------|
| `/flashcards <topic>` | Generate flashcard Q&A pairs |
| `/feynman <topic>` | Feynman technique explanation |
| `/outline <topic>` | Structured outline |
| `/quiz <topic>` | Quiz questions |
| `/ingest <path>` | Ingest file into memory |
| `/obsidian` | Sync Obsidian vault notes |
| `/search <query>` | Semantic search over knowledge base |
| `/brief` or `/briefing` | Generate daily briefing |
| `/stats` | Memory stats |
| `/help` | List commands |
| `/plugin <sub>` | Plugin management |

---

## Logging

Structured logging via `structlog` + `rich`. Import and use:
```python
from logger import get_logger
log = get_logger(__name__)

log.info("event_name", key="value", other=123)
log.warning("event_name", reason="...")
log.error("event_name", error=str(e))
log.debug("event_name", msg=text[:60])
```

Log events use snake_case names. Never use `print()` for operational logging — only for startup banners.

JSON logs are written to `data/logs/` and `logs/jarvis.log`.

---

## Key Conventions

### Code Style
- Python 3.13+ features are used (f-strings, `match` statements, `X | Y` union types)
- Type hints on all function signatures
- Module-level docstrings explaining purpose
- No test suite currently exists — changes are validated by running the server manually
- No linting configuration — follow the style of the surrounding code

### Configuration Access
- Import the `settings` object: `from config.settings import settings`
- Or import module-level constants directly: `from config.settings import LLM_MODEL, AGENT_NAME`
- Never hardcode model names, paths, or ports — always use `settings.*`

### Adding a New Tool
1. Define it with `@tool` from `langchain_core.tools` in `tools/tools.py`
2. Add it to the `ALL_TOOLS` list at the bottom of that file
3. Restart the agent — it will be included in the ReAct graph automatically

### Adding a New API Endpoint
- Add to `main.py` with a Pydantic request model
- Follow the existing pattern: check `if not agent: raise HTTPException(503, ...)`

### Adding a New Slash Command
- Add the handler in `agent/slash_commands.py`
- Return a `CommandResult(prompt=..., pre_response=...)` for LLM-processed commands
- Return `CommandResult(bypass_llm=True, pre_response=...)` for immediate returns

### Data Files (gitignored)
- `data/chroma/` — do not commit; node-local vector store
- `data/sqlite/jarvis.db` — do not commit; node-local conversation history
- `local_settings.py` — do not commit; machine-local platform override
- `.env` — do not commit; contains API keys

---

## Development Workflow

There is no automated test suite or CI/CD pipeline. The development workflow is:

1. **Install dependencies**: `python install.py` or `pip install -r requirements.txt`
2. **Configure**: Copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY` and `JARVIS_PLATFORM`
3. **Run**: `python main.py` (API) or `python cli.py` (terminal)
4. **Test manually**: Use the CLI or `curl` against the API
5. **Benchmarks**: `python -m benchmarks.runner` to run the performance benchmark suite

**Prerequisites:**
- Ollama running locally with the appropriate model pulled: `ollama pull llama3.2`
- For voice: `brew install portaudio` (macOS)
- For PDF: `pymupdf4llm` is included in requirements

**Quick start:**
```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and JARVIS_PLATFORM
pip install -r requirements.txt
python launch.py   # starts Ollama + JARVIS + Open WebUI
```

---

## Important Constraints

- **Do not add tests** unless the user explicitly asks — the project has no test infrastructure.
- **Do not add CI/CD** unless explicitly requested.
- **Do not modify `local_settings.py`** — it is machine-local and gitignored.
- **Do not expand `ALLOWED_SHELL_COMMANDS`** without explicit instruction — this is a security boundary.
- **Do not collapse the dual LLM strategy** — the local/tool split is intentional.
- **Plugin approvals are a human gate** — never auto-approve plugin code generation.
- **Memory context injection goes into the user message**, not a system message (Claude API limitation).
