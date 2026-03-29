"""
PDF Ingestion
-------------
Fast, accurate PDF extraction using PyMuPDF.
Handles lecture slides, textbooks, scanned docs, and mixed-content PDFs.

Pipeline:
  1. pymupdf4llm  — markdown-quality extraction (best for text + slides)
  2. raw text     — page-by-page fallback
  3. OCR          — last resort for image-only / scanned pages

Usage:
    from memory.pdf_ingest import ingest_pdf_to_memory, get_pdf_metadata
    count = ingest_pdf_to_memory(knowledge_memory, "~/lectures/week3.pdf")
    meta  = get_pdf_metadata("textbook.pdf")
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Generator

from logger import get_logger

log = get_logger(__name__)


# ── Page extraction ───────────────────────────────────────────────────────────

def extract_pages(path: str | Path) -> Generator[dict, None, None]:
    """
    Yield one dict per page:
      {"page": int, "text": str, "source": str, "total_pages": int, "method": str}

    Tries pymupdf4llm (markdown-quality), then raw text, then OCR.
    """
    try:
        import fitz          # PyMuPDF
        import pymupdf4llm
    except ImportError as e:
        raise ImportError(
            "PDF support requires: pip install pymupdf pymupdf4llm"
        ) from e

    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = fitz.open(str(path))
    total = len(doc)
    log.info("pdf_opened", file=path.name, pages=total)

    # ── Strategy 1: pymupdf4llm (markdown-quality, great for slides) ─────────
    try:
        md_pages: list[dict] = pymupdf4llm.to_markdown(str(path), page_chunks=True)
        for item in md_pages:
            text = item.get("text", "").strip()
            if not text:
                continue
            yield {
                "page": item.get("metadata", {}).get("page", 0) + 1,
                "text": text,
                "source": str(path),
                "total_pages": total,
                "method": "pymupdf4llm",
            }
        doc.close()
        return
    except Exception as e:
        log.warning("pymupdf4llm_failed", file=path.name, error=str(e), fallback="raw_text")

    # ── Strategy 2: raw text extraction, page by page ─────────────────────────
    for page_num in range(total):
        page = doc[page_num]
        text = page.get_text("text").strip()

        # ── Strategy 3: OCR for image-only pages ──────────────────────────────
        if not text:
            try:
                tp = page.get_textpage_ocr(flags=3, language="eng", dpi=200)
                text = page.get_text("text", textpage=tp).strip()
                method = "ocr"
            except Exception:
                text = f"[Page {page_num + 1}: image-only — OCR unavailable]"
                method = "placeholder"
        else:
            method = "raw"

        if text:
            yield {
                "page": page_num + 1,
                "text": text,
                "source": str(path),
                "total_pages": total,
                "method": method,
            }

    doc.close()


# ── Chunking ──────────────────────────────────────────────────────────────────

def pdf_to_chunks(
    path: str | Path,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[dict]:
    """
    Extract a PDF and split into overlapping text chunks.
    Returns list of dicts: text, source, page, chunk_index, chunk_id, filename.
    """
    path = Path(path)
    all_chunks: list[dict] = []

    for page_data in extract_pages(path):
        text = page_data["text"]
        page_num = page_data["page"]
        start = 0
        while start < len(text):
            chunk_text = text[start: start + chunk_size].strip()
            if chunk_text:
                chunk_id = hashlib.md5(
                    f"{path}|p{page_num}|i{len(all_chunks)}|{chunk_text[:32]}".encode()
                ).hexdigest()
                all_chunks.append({
                    "text": chunk_text,
                    "source": str(path),
                    "page": page_num,
                    "chunk_index": len(all_chunks),
                    "chunk_id": chunk_id,
                    "filename": path.name,
                })
            start += chunk_size - overlap

    log.info("pdf_chunked", file=path.name, chunks=len(all_chunks))
    return all_chunks


# ── Ingest into ChromaDB ──────────────────────────────────────────────────────

def ingest_pdf_to_memory(knowledge_memory, path: str | Path) -> int:
    """
    Full pipeline: extract → chunk → upsert into ChromaDB.

    Args:
        knowledge_memory: a KnowledgeMemory instance (or anything with .collection)
        path: path to the PDF file

    Returns:
        Number of chunks stored.
    """
    from config.settings import settings

    path = Path(path)
    chunks = pdf_to_chunks(
        path,
        chunk_size=settings.memory_chunk_size,
        overlap=settings.memory_overlap,
    )

    if not chunks:
        log.warning("pdf_empty", file=path.name)
        return 0

    ids = [c["chunk_id"] for c in chunks]
    docs = [c["text"] for c in chunks]
    metas = [
        {
            "source": c["source"],
            "page": c["page"],
            "filename": c["filename"],
            "chunk_index": c["chunk_index"],
            "type": "pdf",
        }
        for c in chunks
    ]

    # Support both KnowledgeMemory directly and a shim with .knowledge
    collection = (
        knowledge_memory.collection
        if hasattr(knowledge_memory, "collection")
        else knowledge_memory.knowledge.collection
    )
    collection.upsert(ids=ids, documents=docs, metadatas=metas)

    log.info("pdf_ingested", file=path.name, chunks=len(chunks))
    return len(chunks)


# ── Metadata helper ───────────────────────────────────────────────────────────

def get_pdf_metadata(path: str | Path) -> dict:
    """Return title, author, page count, and file size for a PDF."""
    try:
        import fitz
    except ImportError:
        return {"error": "pymupdf not installed — pip install pymupdf"}

    path = Path(path)
    if not path.exists():
        return {"error": f"File not found: {path}"}

    doc = fitz.open(str(path))
    meta = doc.metadata or {}
    result = {
        "filename": path.name,
        "pages": len(doc),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "subject": meta.get("subject", ""),
        "creator": meta.get("creator", ""),
    }
    doc.close()
    return result
