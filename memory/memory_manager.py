"""
Memory Manager
--------------
Three memory layers:
  1. Episodic  — full conversation history (SQLite)
  2. Semantic  — embedded knowledge base (ChromaDB)
  3. Summary   — long-term facts about the user (SQLite)

Supports text, markdown, code, PDF (via pdf_ingest.py), and Obsidian vaults.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from config.settings import settings
from logger import get_logger

log = get_logger(__name__)


# ── Embedding function ────────────────────────────────────────────────────────

def get_embedding_fn():
    if settings.jarvis_platform != "pi":
        try:
            fn = embedding_functions.OllamaEmbeddingFunction(
                url=f"{settings.ollama_base_url}/api/embeddings",
                model_name=settings.embed_model,
            )
            log.debug("embedding_backend", backend="ollama", model=settings.embed_model)
            return fn
        except Exception as e:
            log.warning("ollama_embed_unavailable", error=str(e), fallback="sentence_transformers")

    fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    log.debug("embedding_backend", backend="sentence_transformers")
    return fn


# ── ChromaDB — semantic knowledge ─────────────────────────────────────────────

class KnowledgeMemory:
    def __init__(self):
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=settings.chroma_path)
        self.embed_fn = get_embedding_fn()
        self.collection = self.client.get_or_create_collection(
            name="jarvis_knowledge",
            embedding_function=self.embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("knowledge_memory_ready", chunks=self.collection.count())

    def ingest_text(self, text: str, source: str, metadata: Optional[dict] = None) -> int:
        chunks = self._chunk(text)
        if not chunks:
            return 0
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{source}_{i}_{chunk[:32]}".encode()).hexdigest()
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "source": source,
                "chunk_index": i,
                "ingested_at": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            })
        self.collection.upsert(ids=ids, documents=docs, metadatas=metas)
        log.info("text_ingested", source=source, chunks=len(chunks))
        return len(chunks)

    def ingest_file(self, filepath: str | Path) -> int:
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        if path.suffix.lower() == ".pdf":
            from memory.pdf_ingest import ingest_pdf_to_memory
            return ingest_pdf_to_memory(self, path)

        if path.stat().st_size > settings.max_file_size_mb * 1024 * 1024:
            raise ValueError(f"File too large (>{settings.max_file_size_mb}MB): {path}")

        text = path.read_text(encoding="utf-8", errors="ignore")
        return self.ingest_text(
            text, source=str(path),
            metadata={"filename": path.name, "type": path.suffix.lstrip(".")},
        )

    def search(self, query: str, n: int = None, where: Optional[dict] = None) -> list[dict]:
        n = n or settings.top_k_results
        count = self.collection.count()
        if count == 0:
            return []
        kwargs: dict = {
            "query_texts": [query[:2000]],   # guard against context overflow
            "n_results": min(n, count),
        }
        if where:
            kwargs["where"] = where
        try:
            results = self.collection.query(**kwargs)
        except Exception as e:
            log.error("search_failed", error=str(e))
            return []
        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "text": doc,
                "source": meta.get("source", ""),
                "score": round(1 - dist, 4),
                "meta": meta,
            })
        return output

    def count(self) -> int:
        return self.collection.count()

    def _chunk(self, text: str) -> list[str]:
        size, overlap = settings.memory_chunk_size, settings.memory_overlap
        chunks, start = [], 0
        while start < len(text):
            chunks.append(text[start: start + size])
            start += size - overlap
        return [c.strip() for c in chunks if c.strip()]


# ── SQLite — episodic memory + summaries ─────────────────────────────────────

class EpisodicMemory:
    def __init__(self):
        Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL UNIQUE,
                content     TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id);
        """)
        self.conn.commit()

    def save_message(self, session_id: str, role: str, content: str):
        self.conn.execute(
            "INSERT INTO conversations (session_id, role, content, timestamp) VALUES (?,?,?,?)",
            (session_id, role, content, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get_history(self, session_id: str, last_n: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, last_n),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def save_summary(self, category: str, content: str):
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """INSERT INTO summaries (category, content, updated_at) VALUES (?,?,?)
               ON CONFLICT(category) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
            (category, content, now),
        )
        self.conn.commit()

    def get_summaries(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT category, content, updated_at FROM summaries"
        ).fetchall()
        return [{"category": c, "content": t, "updated_at": u} for c, t, u in rows]

    def get_summary(self, category: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT content FROM summaries WHERE category=?", (category,)
        ).fetchone()
        return row[0] if row else None


# ── Unified Memory interface ──────────────────────────────────────────────────

class Memory:
    def __init__(self):
        self.knowledge = KnowledgeMemory()
        self.episodic = EpisodicMemory()

    def remember(self, session_id: str, role: str, content: str):
        self.episodic.save_message(session_id, role, content)
        if role == "assistant" and len(content) > 100:
            self.knowledge.ingest_text(content, source=f"session:{session_id}")

    def recall(self, query: str, session_id: str) -> str:
        parts = []
        summaries = self.episodic.get_summaries()
        if summaries:
            parts.append("## What I know about you\n" + "\n".join(
                f"[{s['category']}] {s['content']}" for s in summaries
            ))
        hits = self.knowledge.search(query, n=settings.top_k_results)
        relevant = [h for h in hits if h["score"] > 0.4]
        if relevant:
            parts.append("## Relevant knowledge\n" + "\n\n".join(
                f"[from {h['source']}]\n{h['text']}" for h in relevant
            ))
        return "\n\n---\n\n".join(parts)

    def learn(self, category: str, fact: str):
        self.episodic.save_summary(category, fact)
        log.info("fact_learned", category=category, preview=fact[:60])

    def ingest(self, path: str) -> int:
        return self.knowledge.ingest_file(path)

    def ingest_obsidian(self, vault_path: str | None = None) -> dict:
        vault = Path(vault_path or settings.obsidian_vault_path).expanduser().resolve()
        if not vault.exists():
            raise FileNotFoundError(f"Vault not found: {vault}")
        results: dict = {"ok": [], "errors": []}
        md_files = list(vault.rglob("*.md"))
        log.info("obsidian_sync_start", vault=str(vault), files=len(md_files))
        for f in md_files:
            try:
                n = self.knowledge.ingest_file(f)
                results["ok"].append({"file": f.name, "chunks": n})
            except Exception as e:
                results["errors"].append({"file": f.name, "error": str(e)})
        log.info("obsidian_sync_done", ok=len(results["ok"]), errors=len(results["errors"]))
        return results


    def search_conversations(self, query: str, n: int = 5) -> list[dict]:
        """Semantic search over past conversation turns stored in ChromaDB."""
        hits = self.knowledge.search(query, n=n * 3)
        results = []
        for h in hits:
            source = h["source"]
            if source.startswith("session:"):
                results.append({
                    "text": h["text"],
                    "session_id": source.replace("session:", ""),
                    "score": h["score"],
                    "ingested_at": h["meta"].get("ingested_at", ""),
                })
            if len(results) >= n:
                break
        return results

    def stats(self) -> dict:
        return {
            "knowledge_chunks": self.knowledge.count(),
            "summaries": len(self.episodic.get_summaries()),
        }
