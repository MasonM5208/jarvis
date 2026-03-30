"""
JARVIS Configuration
--------------------
Platform resolution order (first match wins):
  1. local_settings.py  — gitignored, machine-local, never touched by git pull
  2. JARVIS_PLATFORM env var  — set in .env or systemd EnvironmentFile
  3. Default: "mac"
"""

import os
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ── Platform resolution ───────────────────────────────────────────────────────
def _resolve_platform() -> str:
    # 1. local_settings.py (gitignored, never overwritten by git pull)
    local = BASE_DIR / "local_settings.py"
    if local.exists():
        _locals: dict = {}
        exec(local.read_text(), _locals)
        if "PLATFORM" in _locals:
            return _locals["PLATFORM"]
    # 2. Environment variable
    env = os.getenv("JARVIS_PLATFORM")
    if env:
        return env
    # 3. Default
    return "mac"

PLATFORM = _resolve_platform()

# ── Model backend ─────────────────────────────────────────────────────────────
if PLATFORM == "mac":
    LLM_BACKEND   = "ollama"
    LLM_MODEL     = "llama3.2"
    LLM_BASE_URL  = "http://localhost:11434"
    EMBED_MODEL   = "nomic-embed-text"
elif PLATFORM == "pc":
    LLM_BACKEND   = "ollama"
    LLM_MODEL     = "llama3.1:8b"
    LLM_BASE_URL  = "http://localhost:11434"
    EMBED_MODEL   = "nomic-embed-text"
else:  # pi
    LLM_BACKEND   = "llama_cpp"
    LLM_MODEL     = "llama3.2-3b"
    LLM_BASE_URL  = "http://localhost:8080"
    EMBED_MODEL   = "all-MiniLM-L6-v2"

# ── Memory ────────────────────────────────────────────────────────────────────
CHROMA_PATH   = str(DATA_DIR / "chroma")
SQLITE_PATH   = str(DATA_DIR / "sqlite" / "jarvis.db")
UPLOADS_PATH  = str(DATA_DIR / "uploads")

TOP_K_RESULTS      = 5
MEMORY_CHUNK_SIZE  = 512
MEMORY_OVERLAP     = 64

# ── Agent behaviour ───────────────────────────────────────────────────────────
AGENT_NAME        = "JARVIS"
MAX_ITERATIONS    = 10
TEMPERATURE       = 0.7
CONTEXT_WINDOW    = 4096
SYSTEM_PROMPT     = f"""You are {AGENT_NAME}, a personal AI assistant and second brain.
You have access to the user's files, memory, and system tools.
You help with college work, self-study, research, and project thinking.
When you learn something new about the user, their projects, or their goals,
note it for future reference. Be concise, direct, and intellectually honest.
Always think step by step before using a tool."""

# ── Tools ─────────────────────────────────────────────────────────────────────
ALLOWED_SHELL_COMMANDS = [
    "ls", "cat", "echo", "pwd", "find", "grep", "python3",
    "git", "pip", "brew",
]
MAX_FILE_SIZE_MB = 10

# ── Voice ─────────────────────────────────────────────────────────────────────
VOICE_ENABLED  = True
TTS_ENABLED    = True
WHISPER_MODEL  = os.getenv("JARVIS_WHISPER", "base")

# ── Camera (Pi only) ─────────────────────────────────────────────────────────
CAMERA_ENABLED    = PLATFORM == "pi"
CAMERA_RESOLUTION = (1280, 720)

# ── Settings object (agent.py compatibility) ──────────────────────────────────
class _Settings:
    llm_backend            = LLM_BACKEND
    llm_model              = LLM_MODEL
    llm_base_url           = LLM_BASE_URL
    ollama_base_url        = LLM_BASE_URL
    embed_model            = EMBED_MODEL
    temperature            = TEMPERATURE
    context_window         = CONTEXT_WINDOW
    max_iterations         = MAX_ITERATIONS
    agent_name             = AGENT_NAME
    system_prompt          = SYSTEM_PROMPT
    allowed_shell_commands = ALLOWED_SHELL_COMMANDS
    max_file_size_mb       = MAX_FILE_SIZE_MB
    top_k_results          = TOP_K_RESULTS
    memory_chunk_size      = MEMORY_CHUNK_SIZE
    memory_overlap         = MEMORY_OVERLAP
    chroma_path            = CHROMA_PATH
    sqlite_path            = SQLITE_PATH
    uploads_path           = str(DATA_DIR / "uploads")
    plugins_dir            = DATA_DIR.parent / "plugins"
    log_level              = "INFO"
    log_format             = "json"
    log_file               = str(DATA_DIR / "jarvis.log")
    jarvis_host            = "0.0.0.0"
    jarvis_port            = 8000
    jarvis_platform        = PLATFORM
    jarvis_api_token       = os.getenv("JARVIS_API_TOKEN", "")
    anthropic_api_key      = os.getenv("ANTHROPIC_API_KEY", "")
    obsidian_vault_path    = os.getenv(
        "OBSIDIAN_VAULT",
        str(Path.home() / "Documents" / "Mason's Vault")
    )

settings = _Settings()
