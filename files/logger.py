"""
JARVIS Structured Logging
--------------------------
Provides a consistent, structured logger across all modules.

Usage:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("server_started", port=8000, model="llama3.2")
    log.error("tool_failed", tool="web_search", error=str(e))

JSON output (production):
    {"event": "server_started", "port": 8000, "level": "info", "timestamp": "..."}

Console output (development):
    12:00:00 [INFO ] main › server_started  port=8000 model=llama3.2
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def _setup(log_level: str = "INFO", log_format: str = "console", log_file: str | None = None):
    """Configure structlog + stdlib logging. Call once at startup via init_logging()."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        final_processor = structlog.processors.JSONRenderer()
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=final_processor,
            foreign_pre_chain=shared_processors,
        )
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
    else:
        # Rich colored console
        try:
            from rich.console import Console
            from rich.logging import RichHandler
            _console = Console(stderr=True)
            handler = RichHandler(
                console=_console,
                show_path=False,
                markup=True,
                rich_tracebacks=True,
            )
        except ImportError:
            handler = logging.StreamHandler(sys.stderr)

        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=(log_format != "json")),
            foreign_pre_chain=shared_processors,
        )
        handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [handler]

    # Optional file handler — always JSON for easy parsing / grep
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(path))
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "chromadb", "sentence_transformers",
                  "langchain", "langsmith", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for the given module name."""
    return structlog.get_logger(name)


def init_logging():
    """Call this once from main.py / daemon.py after settings are loaded."""
    try:
        from config.settings import settings
        _setup(
            log_level=settings.log_level,
            log_format=settings.log_format,
            log_file=settings.log_file,
        )
    except Exception:
        _setup()  # Fallback — always get a logger even if settings fail
