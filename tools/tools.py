"""
Tool Registry
-------------
All base agent tools. Each tool is a plain Python function decorated with @tool.
The agent reads each docstring to decide when to call it.

Adding a new tool: write function + add @tool + append to ALL_TOOLS. That's it.
For dynamically generated tools, see tools/plugin_registry.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from datetime import datetime
from typing import Annotated

from langchain_core.tools import tool

from config.settings import settings
from logger import get_logger

log = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


# ── File tools ────────────────────────────────────────────────────────────────

@tool
def read_file(path: Annotated[str, "Absolute or ~ path to the file"]) -> str:
    """Read the contents of a text file and return it."""
    p = _safe_path(path)
    if not p.exists():
        return f"Error: File not found — {p}"
    if p.stat().st_size > settings.max_file_size_mb * 1024 * 1024:
        return f"Error: File too large (>{settings.max_file_size_mb}MB)"
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        log.error("read_file_failed", path=str(p), error=str(e))
        return f"Error reading file: {e}"


@tool
def write_file(
    path: Annotated[str, "Path to write to"],
    content: Annotated[str, "Text content to write"],
) -> str:
    """Create or overwrite a file with the given content."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(content, encoding="utf-8")
        log.info("file_written", path=str(p), chars=len(content))
        return f"Written {len(content)} chars to {p}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def append_file(
    path: Annotated[str, "Path to append to"],
    content: Annotated[str, "Text to append"],
) -> str:
    """Append content to an existing file (or create it if it doesn't exist)."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} chars to {p}"
    except Exception as e:
        return f"Error appending to file: {e}"


@tool
def list_directory(path: Annotated[str, "Directory path to list"]) -> str:
    """List files and subdirectories at a given path."""
    p = _safe_path(path)
    if not p.is_dir():
        return f"Error: Not a directory — {p}"
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for e in entries:
            size = f"  {e.stat().st_size:>10,} bytes" if e.is_file() else "  <dir>"
            lines.append(f"{'📁' if e.is_dir() else '📄'} {e.name}{size}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


@tool
def search_files(
    directory: Annotated[str, "Directory to search in"],
    pattern: Annotated[str, "Glob pattern, e.g. '*.py' or '**/*.md'"],
) -> str:
    """Recursively search for files matching a glob pattern."""
    p = _safe_path(directory)
    try:
        matches = list(p.glob(pattern))[:50]
        return "\n".join(str(m) for m in matches) or "No matches found."
    except Exception as e:
        return f"Error searching files: {e}"


@tool
def create_directory(path: Annotated[str, "Directory path to create"]) -> str:
    """Create a directory (and any missing parents)."""
    p = _safe_path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {p}"
    except Exception as e:
        return f"Error creating directory: {e}"


# ── Shell tools ───────────────────────────────────────────────────────────────

@tool
def run_shell(
    command: Annotated[str, "Shell command to run"],
    working_dir: Annotated[str, "Working directory (optional)"] = "~",
) -> str:
    """
    Run an approved shell command and return stdout + stderr.
    Only pre-approved commands are allowed for safety.
    """
    cmd_name = command.strip().split()[0]
    if cmd_name not in settings.allowed_shell_commands:
        return (
            f"Error: '{cmd_name}' is not in the allowed command list.\n"
            f"Allowed: {', '.join(settings.allowed_shell_commands)}"
        )
    cwd = _safe_path(working_dir) if working_dir != "~" else Path.home()
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=30,
        )
        out, err = result.stdout.strip(), result.stderr.strip()
        log.debug("shell_run", cmd=command[:60], returncode=result.returncode)
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr] {err}")
        return "\n".join(parts) or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as e:
        return f"Error running command: {e}"


@tool
def run_python(
    code: Annotated[str, "Python code to execute"],
    working_dir: Annotated[str, "Working directory"] = "~",
) -> str:
    """Execute a Python code snippet and return its output."""
    import tempfile
    cwd = _safe_path(working_dir)
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            ["python3", tmp], cwd=cwd,
            capture_output=True, text=True, timeout=60,
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        return out if out else (f"[stderr] {err}" if err else "(no output)")
    except subprocess.TimeoutExpired:
        return "Error: Execution timed out."
    finally:
        Path(tmp).unlink(missing_ok=True)


# ── macOS tools ───────────────────────────────────────────────────────────────

@tool
def run_applescript(script: Annotated[str, "AppleScript code to run"]) -> str:
    """
    Run an AppleScript. Use to control macOS apps, read calendar,
    send notifications, open files, or control system settings.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or result.stderr.strip() or "(no output)"
    except Exception as e:
        return f"Error running AppleScript: {e}"


@tool
def send_notification(
    title: Annotated[str, "Notification title"],
    message: Annotated[str, "Notification body"],
) -> str:
    """Send a macOS system notification."""
    script = f'display notification "{message}" with title "{title}"'
    return run_applescript.invoke(script)


@tool
def open_application(
    app_name: Annotated[str, "Application name, e.g. 'Safari', 'Notes', 'Terminal'"],
) -> str:
    """Open a macOS application by name."""
    try:
        subprocess.run(["open", "-a", app_name], check=True, timeout=10)
        return f"Opened {app_name}"
    except subprocess.CalledProcessError:
        return f"Error: Could not open '{app_name}' — check the app name."
    except Exception as e:
        return f"Error: {e}"


@tool
def get_current_datetime() -> str:
    """Return the current date and time."""
    return datetime.now().strftime("%A, %B %d %Y at %I:%M %p")


# ── Web tools ─────────────────────────────────────────────────────────────────

@tool
def web_search(query: Annotated[str, "Search query"]) -> str:
    """
    Search the web using DuckDuckGo (no API key needed).
    Returns a summary of the top results.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "Error: Install ddgs — pip install ddgs"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No results found."
        log.debug("web_search", query=query[:50], results=len(results))
        return "\n\n".join(
            f"**{r['title']}**\n{r['body']}\n{r['href']}" for r in results
        )
    except Exception as e:
        return f"Search error: {e}"


@tool
def fetch_webpage(url: Annotated[str, "URL to fetch"]) -> str:
    """Fetch and return the readable text content of a webpage."""
    try:
        import httpx
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (compatible; JARVIS/2.0)"}
        r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        log.debug("fetch_webpage", url=url[:60], chars=len(text))
        return text[:8000]
    except Exception as e:
        return f"Error fetching page: {e}"


# ── Memory stubs (wired to real memory in agent.py) ───────────────────────────

@tool
def remember_fact(
    category: Annotated[str, "Category label, e.g. 'current_projects', 'user_goals'"],
    fact: Annotated[str, "The fact or summary to store"],
) -> str:
    """Store a long-term fact about the user or their work that should persist across sessions."""
    return f"[stub — wired in agent.py] category={category}"


@tool
def ingest_document(
    path: Annotated[str, "Path to a text, markdown, code, or PDF file to learn from"],
) -> str:
    """Ingest a document into the knowledge base so it can be recalled in future conversations."""
    return f"[stub — wired in agent.py] path={path}"


# ── Tool list ─────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    read_file,
    write_file,
    append_file,
    list_directory,
    search_files,
    create_directory,
    run_shell,
    run_python,
    run_applescript,
    send_notification,
    open_application,
    get_current_datetime,
    web_search,
    fetch_webpage,
    remember_fact,
    ingest_document,
]
