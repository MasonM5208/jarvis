"""
Dynamic Plugin Registry
------------------------
When JARVIS hits a capability gap, it can:
  1. Ask Claude API to write a new plugin
  2. Show the generated code to the user for review
  3. Save it to plugins/ on approval
  4. Load it at runtime without a restart

Plugin lifecycle:
  PENDING  → code drafted, awaiting user approval
  APPROVED → saved to plugins/, loaded into the tool registry
  REJECTED → discarded

Usage:
    from tools.plugin_registry import PluginRegistry
    registry = PluginRegistry(base_tools=ALL_TOOLS)
    all_tools = registry.get_all_tools()   # base + approved plugins
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import sqlite3
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Callable, Optional

from config.settings import settings
from logger import get_logger

log = get_logger(__name__)

PLUGINS_DIR = settings.plugins_dir
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

if str(PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGINS_DIR))


# ── Plugin metadata (SQLite) ──────────────────────────────────────────────────

class PluginStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init()

    def _init(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS plugins (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                code        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                filename    TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def save(self, name: str, description: str, code: str) -> int:
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            """INSERT INTO plugins (name, description, code, status, created_at, updated_at)
               VALUES (?,?,?,'pending',?,?)
               ON CONFLICT(name) DO UPDATE SET
                 code=excluded.code, description=excluded.description,
                 status='pending', updated_at=excluded.updated_at""",
            (name, description, code, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def approve(self, name: str, filename: str):
        self.conn.execute(
            "UPDATE plugins SET status='approved', filename=?, updated_at=? WHERE name=?",
            (filename, datetime.now(UTC).isoformat(), name),
        )
        self.conn.commit()

    def reject(self, name: str):
        self.conn.execute(
            "UPDATE plugins SET status='rejected', updated_at=? WHERE name=?",
            (datetime.now(UTC).isoformat(), name),
        )
        self.conn.commit()

    def get(self, name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT name, description, code, status, filename, created_at FROM plugins WHERE name=?",
            (name,),
        ).fetchone()
        if not row:
            return None
        return dict(zip(["name", "description", "code", "status", "filename", "created_at"], row))

    def list_approved(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, description, filename FROM plugins WHERE status='approved'"
        ).fetchall()
        return [{"name": r[0], "description": r[1], "filename": r[2]} for r in rows]

    def list_pending(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, description, code FROM plugins WHERE status='pending'"
        ).fetchall()
        return [{"name": r[0], "description": r[1], "code": r[2]} for r in rows]


# ── Code generation (Claude API) ──────────────────────────────────────────────

_PLUGIN_SYSTEM_PROMPT = """You are writing a Python tool plugin for JARVIS, a personal AI assistant.

Generate a single self-contained Python function decorated with @tool from langchain_core.tools.
Follow this exact structure:

```python
from typing import Annotated
from langchain_core.tools import tool

@tool
def tool_name(
    param1: Annotated[str, "Description of param1"],
    param2: Annotated[int, "Description of param2"] = 0,
) -> str:
    \"\"\"One clear sentence describing what this tool does and when to use it.\"\"\"
    # implementation
    return "result"
```

Rules:
- Function name must be lowercase with underscores
- All parameters must have Annotated type hints with clear descriptions
- Docstring must clearly describe when the agent should call this tool
- Use only stdlib + packages in requirements.txt (httpx, beautifulsoup4, etc.)
- Handle errors gracefully and return descriptive error strings
- Use lazy imports inside the function body if the import might fail
- Return ONLY the Python code block, no explanation or prose
"""


def generate_plugin_code(request: str) -> tuple[str, str]:
    """
    Ask Claude to write a plugin. Returns (tool_name, code).
    Requires ANTHROPIC_API_KEY in .env.
    """
    import httpx

    api_key = settings.anthropic_api_key
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set — add it to .env to enable plugin generation"
        )

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 2000,
            "system": _PLUGIN_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": f"Write a JARVIS tool for: {request}"}],
        },
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()["content"][0]["text"].strip()

    # Extract code block
    match = re.search(r"```python\n(.*?)```", raw, re.DOTALL)
    code = match.group(1).strip() if match else raw

    # Extract function name
    name_match = re.search(r"^def (\w+)", code, re.MULTILINE)
    tool_name = name_match.group(1) if name_match else "custom_tool"

    log.info("plugin_generated", tool_name=tool_name, code_lines=len(code.splitlines()))
    return tool_name, code


# ── Plugin loader ─────────────────────────────────────────────────────────────

def load_plugin_from_file(filepath: Path) -> Optional[Callable]:
    """Dynamically load a @tool decorated function from a .py file."""
    try:
        spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module):
            if hasattr(obj, "name") and hasattr(obj, "invoke") and hasattr(obj, "description"):
                log.info("plugin_loaded", name=name, file=filepath.name)
                return obj

        log.warning("plugin_no_tool_found", file=filepath.name)
        return None
    except Exception as e:
        log.error("plugin_load_failed", file=str(filepath), error=str(e))
        return None


# ── Plugin Registry ───────────────────────────────────────────────────────────

class PluginRegistry:
    """Manages the full lifecycle: request → generate → review → approve → load."""

    def __init__(self, base_tools: list):
        self.base_tools = list(base_tools)
        self._loaded: dict[str, Callable] = {}
        self.store = PluginStore(
            settings.sqlite_path.replace(".db", "_plugins.db")
        )
        self._restore_approved()

    def _restore_approved(self):
        """Re-load all previously approved plugins from disk on startup."""
        for plugin in self.store.list_approved():
            if plugin["filename"]:
                path = PLUGINS_DIR / plugin["filename"]
                if path.exists():
                    fn = load_plugin_from_file(path)
                    if fn:
                        self._loaded[plugin["name"]] = fn
        if self._loaded:
            log.info("plugins_restored", count=len(self._loaded))

    def get_all_tools(self) -> list:
        """Return base tools + all approved loaded plugins."""
        return self.base_tools + list(self._loaded.values())

    def request_plugin(self, request: str) -> dict:
        """
        Ask Claude to draft a plugin. Returns the code for user review.
        Does NOT load or save anything — user must approve() first.
        """
        log.info("plugin_request", request=request[:80])
        tool_name, code = generate_plugin_code(request)
        self.store.save(tool_name, request, code)
        return {
            "status": "pending",
            "name": tool_name,
            "code": code,
            "message": (
                f"Plugin `{tool_name}` drafted — review the code above, then:\n"
                f"  `/plugin approve {tool_name}` to load it\n"
                f"  `/plugin reject {tool_name}` to discard it"
            ),
        }

    def approve_plugin(self, name: str) -> dict:
        """Save approved plugin to disk and hot-load it into the tool registry."""
        plugin = self.store.get(name)
        if not plugin:
            return {"error": f"Plugin '{name}' not found"}
        if plugin["status"] == "approved":
            return {"status": "already_approved", "name": name, "message": f"Plugin `{name}` is already loaded"}

        filename = f"{name}.py"
        filepath = PLUGINS_DIR / filename

        try:
            filepath.write_text(plugin["code"], encoding="utf-8")
            fn = load_plugin_from_file(filepath)
            if not fn:
                filepath.unlink(missing_ok=True)
                return {"error": f"No @tool function found in generated code for '{name}'"}

            self._loaded[name] = fn
            self.store.approve(name, filename)
            log.info("plugin_approved", name=name, file=filename)
            return {
                "status": "approved",
                "name": name,
                "message": f"✅ Plugin `{name}` loaded and ready to use",
            }
        except Exception as e:
            log.error("plugin_approve_failed", name=name, error=str(e))
            return {"error": str(e)}

    def reject_plugin(self, name: str) -> dict:
        self.store.reject(name)
        log.info("plugin_rejected", name=name)
        return {"status": "rejected", "name": name}

    def list_plugins(self) -> dict:
        return {
            "loaded": list(self._loaded.keys()),
            "pending": [p["name"] for p in self.store.list_pending()],
            "approved": [p["name"] for p in self.store.list_approved()],
        }

    def get_pending_code(self, name: str) -> Optional[str]:
        plugin = self.store.get(name)
        return plugin["code"] if plugin else None
