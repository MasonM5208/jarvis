"""
JARVIS Configuration
--------------------
All settings loaded from .env file (or environment variables).
Import: from config.settings import settings

Never hardcode secrets — use .env.
Copy .env.example to .env to get started.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve().parent   # config/
BASE_DIR = _HERE.parent                   # jarvis/
_ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Platform ──────────────────────────────────────────────────────────────
    jarvis_platform: Literal["mac", "pi", "pc"] = Field("mac", alias="JARVIS_PLATFORM")

    # ── API keys ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    # ── Ollama (Mac / PC) ─────────────────────────────────────────────────────
    ollama_base_url: str = Field("http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("llama3.2", alias="OLLAMA_MODEL")
    ollama_embed_model: str = Field("nomic-embed-text", alias="OLLAMA_EMBED_MODEL")

    # ── llama.cpp (Pi) ────────────────────────────────────────────────────────
    llama_cpp_base_url: str = Field("http://localhost:8080", alias="LLAMA_CPP_BASE_URL")
    llama_cpp_model: str = Field("llama3.2-1b-hef", alias="LLAMA_CPP_MODEL")

    # ── API server ────────────────────────────────────────────────────────────
    jarvis_port: int = Field(8000, alias="JARVIS_PORT")
    jarvis_host: str = Field("0.0.0.0", alias="JARVIS_HOST")
    jarvis_api_token: str = Field("", alias="JARVIS_API_TOKEN")

    # ── Memory ────────────────────────────────────────────────────────────────
    chroma_path: str = Field("./data/chroma", alias="CHROMA_PATH")
    sqlite_path: str = Field("./data/sqlite/jarvis.db", alias="SQLITE_PATH")
    uploads_path: str = Field("./data/uploads", alias="UPLOADS_PATH")
    top_k_results: int = Field(5, alias="TOP_K_RESULTS")
    memory_chunk_size: int = Field(512, alias="MEMORY_CHUNK_SIZE")
    memory_overlap: int = Field(64, alias="MEMORY_OVERLAP")

    # ── Agent ─────────────────────────────────────────────────────────────────
    agent_name: str = Field("JARVIS", alias="AGENT_NAME")
    max_iterations: int = Field(10, alias="MAX_ITERATIONS")
    temperature: float = Field(0.7, alias="TEMPERATURE")
    context_window: int = Field(4096, alias="CONTEXT_WINDOW")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO", alias="LOG_LEVEL")
    log_format: Literal["json", "console"] = Field("console", alias="LOG_FORMAT")
    log_file: str = Field("./logs/jarvis.log", alias="LOG_FILE")

    # ── Obsidian ──────────────────────────────────────────────────────────────
    obsidian_vault_path: str = Field("~/Documents/Obsidian", alias="OBSIDIAN_VAULT_PATH")

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice_enabled: bool = Field(False, alias="VOICE_ENABLED")
    whisper_model: str = Field("base", alias="WHISPER_MODEL")

    # ── Tools ─────────────────────────────────────────────────────────────────
    allowed_shell_commands: list[str] = Field(
        default=["ls", "cat", "echo", "pwd", "find", "grep", "python3", "git", "pip", "brew"],
    )
    max_file_size_mb: int = 10

    @field_validator("chroma_path", "sqlite_path", "uploads_path", "log_file", mode="before")
    @classmethod
    def resolve_relative_paths(cls, v: str) -> str:
        p = Path(v).expanduser()
        if not p.is_absolute():
            p = BASE_DIR / p
        return str(p)

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def llm_backend(self) -> str:
        return "hailo" if self.jarvis_platform == "pi" else "ollama"

    @property
    def llm_model(self) -> str:
        return self.llama_cpp_model if self.jarvis_platform == "pi" else self.ollama_model

    @property
    def llm_base_url(self) -> str:
        return self.llama_cpp_base_url if self.jarvis_platform == "pi" else self.ollama_base_url

    @property
    def embed_model(self) -> str:
        return "all-MiniLM-L6-v2" if self.jarvis_platform == "pi" else self.ollama_embed_model

    @property
    def plugins_dir(self) -> Path:
        return BASE_DIR / "plugins"

    @property
    def system_prompt(self) -> str:
        return f"""You are {self.agent_name}, a personal AI assistant and second brain.
You have access to the user's files, memory, and system tools.
You help with college work, self-study, research, and project thinking.
When you learn something important about the user, their projects, or their goals, store it.
Be concise, direct, and intellectually honest. Think step by step before using a tool.

Slash commands you understand:
  /flashcards <topic>    → generate Anki-style Q&A cards
  /feynman <topic>       → explain a concept using the Feynman technique
  /outline <topic>       → create a structured study outline
  /quiz <topic>          → generate a self-assessment quiz
  /ingest <path>         → ingest a file or directory into memory
  /obsidian [path]       → sync and ingest the Obsidian vault
  /plugin request <desc> → request a new JARVIS capability be built
  /plugin list           → list installed plugins
  /plugin approve <name> → approve and load a pending plugin
  /plugin reject <name>  → reject a pending plugin
  /help                  → show all commands"""


# ── Singleton ─────────────────────────────────────────────────────────────────
settings = Settings()

# ── Legacy aliases (keeps existing code working without changes) ──────────────
LLM_MODEL = settings.llm_model
LLM_BACKEND = settings.llm_backend
LLM_BASE_URL = settings.llm_base_url
EMBED_MODEL = settings.embed_model
AGENT_NAME = settings.agent_name
SYSTEM_PROMPT = settings.system_prompt
CHROMA_PATH = settings.chroma_path
SQLITE_PATH = settings.sqlite_path
UPLOADS_PATH = settings.uploads_path
TOP_K_RESULTS = settings.top_k_results
MEMORY_CHUNK_SIZE = settings.memory_chunk_size
MEMORY_OVERLAP = settings.memory_overlap
MAX_ITERATIONS = settings.max_iterations
TEMPERATURE = settings.temperature
CONTEXT_WINDOW = settings.context_window
ALLOWED_SHELL_COMMANDS = settings.allowed_shell_commands
MAX_FILE_SIZE_MB = settings.max_file_size_mb
