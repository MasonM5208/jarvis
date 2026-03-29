"""
JARVIS Web Clipper
------------------
Fetches a URL, extracts clean text, and ingests it into the knowledge base.

Usage:
    # From Python
    from clipper import clip
    result = clip("https://example.com/article", tags=["research", "ml"])

    # From CLI
    python clipper.py https://example.com/article research ml
    python clipper.py --bookmarklet   # print browser bookmarklet JS

    # Via API (triggered by browser bookmarklet)
    POST /clip  {"url": "...", "tags": ["..."]}

Bookmarklet:
    Run `python clipper.py --bookmarklet` to get JavaScript you can save
    as a browser bookmark. Clicking it clips the current page into JARVIS.
"""

from __future__ import annotations

import os
import re
import sys
import warnings
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlparse

warnings.filterwarnings("ignore")

# ── SSL fix (must be before httpx import) ─────────────────────────────────────
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import httpx
from bs4 import BeautifulSoup

# Add jarvis/ to path so memory imports work when run as a script
_JARVIS_DIR = Path(__file__).resolve().parent
if str(_JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(_JARVIS_DIR))

from memory.memory_manager import KnowledgeMemory
from logger import get_logger

log = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Fetchers ──────────────────────────────────────────────────────────────────

def _scrape_page(url: str) -> dict:
    """General-purpose scraper with content extraction."""
    r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True, verify=False)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Metadata
    og_title = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    title = (
        (og_title.get("content", "") if og_title else "")
        or (title_tag.string or "" if title_tag else "")
        or urlparse(url).netloc
    ).strip()

    og_desc = soup.find("meta", property="og:description")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = (
        (og_desc.get("content", "") if og_desc else "")
        or (meta_desc.get("content", "") if meta_desc else "")
    ).strip()

    author_meta = soup.find("meta", attrs={"name": "author"})
    author = (author_meta.get("content", "") if author_meta else "").strip()

    # Clean DOM
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "iframe", "noscript", "form", "button", "svg"]):
        tag.decompose()

    # Find main content block
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"article|content|post|entry", re.I))
        or soup.find("body")
    )
    raw_text = main.get_text(separator="\n", strip=True) if main else soup.get_text()
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip() and len(ln.strip()) > 20]
    clean_text = "\n".join(lines)

    return {
        "url": url,
        "title": title,
        "description": description,
        "author": author,
        "text": clean_text,
        "clipped_at": datetime.now(UTC).isoformat(),
        "domain": urlparse(url).netloc,
        "word_count": len(clean_text.split()),
    }


def _fetch_wikipedia(url: str) -> dict:
    """Use the Wikipedia API for much cleaner text than scraping."""
    try:
        import wikipediaapi
    except ImportError:
        return _scrape_page(url)

    title_slug = url.split("/wiki/")[-1].replace("_", " ")
    wiki = wikipediaapi.Wikipedia(language="en", user_agent="JARVIS-Personal-Agent/2.0")
    page = wiki.page(title_slug)

    if not page.exists():
        return _scrape_page(url)

    text = page.text
    return {
        "url": url,
        "title": page.title,
        "description": "",
        "author": "Wikipedia",
        "text": text,
        "clipped_at": datetime.now(UTC).isoformat(),
        "domain": "en.wikipedia.org",
        "word_count": len(text.split()),
    }


def _fetch(url: str) -> dict:
    if "wikipedia.org/wiki/" in url:
        return _fetch_wikipedia(url)
    return _scrape_page(url)


# ── Main clip function ────────────────────────────────────────────────────────

def clip(url: str, tags: list[str] | None = None) -> dict:
    """
    Clip a URL into the JARVIS knowledge base.

    Args:
        url:  The URL to fetch and ingest.
        tags: Optional list of tag strings for metadata.

    Returns:
        Dict with title, word_count, chunks_stored, url, domain, clipped_at.
    """
    tags = tags or []
    log.info("clip_start", url=url, tags=tags)

    page = _fetch(url)
    log.info("clip_fetched", title=page["title"], words=page["word_count"])

    # Build the document to ingest
    content = "\n".join([
        f"# {page['title']}",
        f"Source: {page['url']}",
        f"Domain: {page['domain']}",
        f"Clipped: {page['clipped_at']}",
        f"Author: {page.get('author', '')}",
        f"Description: {page.get('description', '')}",
        f"Tags: {', '.join(tags)}",
        "",
        "---",
        "",
        page["text"],
    ])

    memory = KnowledgeMemory()
    n = memory.ingest_text(
        content,
        source=url,
        metadata={
            "type": "web_clip",
            "title": page["title"],
            "domain": page["domain"],
            "clipped_at": page["clipped_at"],
            "tags": ",".join(tags),
        },
    )

    log.info("clip_done", title=page["title"], chunks=n)
    return {**page, "chunks_stored": n}


# ── Bookmarklet generator ─────────────────────────────────────────────────────

def print_bookmarklet(port: int = 8000):
    """Print a JavaScript bookmarklet that clips the current page into JARVIS."""
    js = (
        "javascript:(function(){"
        f"fetch('http://localhost:{port}/clip',{{"
        "method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({url:window.location.href})"
        "}).then(r=>r.json())"
        ".then(d=>alert('Clipped: '+(d.title||'page')+' | '+d.chunks_stored+' chunks'))"
        ".catch(()=>alert('JARVIS not running on :{port}'))"
        "})();"
    )
    print("\n" + "=" * 64)
    print("  Drag this to your bookmarks bar:")
    print()
    print(js)
    print()
    print("  Or add as a bookmark with the above as the URL.")
    print("  Clicking it will clip the current page into JARVIS.")
    print("=" * 64 + "\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or args[0] in ("--bookmarklet", "-b"):
        print_bookmarklet()
        return

    url = args[0]
    tags = args[1:] if len(args) > 1 else []

    if not url.startswith("http"):
        url = "https://" + url

    try:
        result = clip(url, tags)
        print(f"\n✅ Clipped: \"{result['title']}\"")
        print(f"   Domain:  {result['domain']}")
        print(f"   Words:   {result['word_count']:,}")
        print(f"   Chunks:  {result['chunks_stored']} stored in knowledge base\n")
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP error {e.response.status_code}: {url}")
    except httpx.ConnectError:
        print(f"❌ Could not connect to: {url}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
