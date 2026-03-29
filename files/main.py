"""
JARVIS API Server (FastAPI)
---------------------------
OpenAI-compatible API on http://localhost:8000
Connects to Open WebUI, CLI, and hotkey app with zero config.

Start with: python main.py

Dashboard: http://localhost:8000/ui/dashboard.html
"""

from __future__ import annotations

import os
import uuid
import time
import json
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

# ── Boot: logging + SSL must be configured before other imports ───────────────
from logger import init_logging
init_logging()
from logger import get_logger
log = get_logger(__name__)

import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.settings import settings
from agent.agent import JarvisAgent


# ── Optional auth ─────────────────────────────────────────────────────────────

async def verify_token(authorization: Optional[str] = Header(None)):
    """If JARVIS_API_TOKEN is set, require it as a Bearer token."""
    if not settings.jarvis_api_token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1]
    if token != settings.jarvis_api_token:
        raise HTTPException(403, "Invalid API token")


# ── App lifecycle ─────────────────────────────────────────────────────────────

agent: Optional[JarvisAgent] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    log.info("jarvis_starting", model=settings.llm_model, platform=settings.jarvis_platform)
    agent = JarvisAgent()
    yield
    log.info("jarvis_stopping")

app = FastAPI(title="JARVIS", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the admin dashboard at /ui
_interface_dir = Path(__file__).parent / "interface"
if _interface_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_interface_dir), html=True), name="ui")


# ── Request models ────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = settings.llm_model
    messages: list[Message]
    stream: bool = False
    session_id: Optional[str] = None

class IngestRequest(BaseModel):
    path: str

class ClipRequest(BaseModel):
    url: str
    tags: list[str] = []

class ObsidianSyncRequest(BaseModel):
    vault_path: Optional[str] = None

class PluginActionRequest(BaseModel):
    action: str   # "request" | "approve" | "reject" | "list"
    name: Optional[str] = None
    request: Optional[str] = None


# ── OpenAI-compatible endpoints ───────────────────────────────────────────────

@app.get("/v1/models", dependencies=[Depends(verify_token)])
async def list_models():
    return {
        "object": "list",
        "data": [{"id": settings.llm_model, "object": "model", "owned_by": settings.agent_name}],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(verify_token)])
async def chat_completions(req: ChatRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")

    user_message = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )
    session_id = req.session_id or str(uuid.uuid4())
    log.info("chat_request", session_id=session_id, message_preview=user_message[:60])

    if req.stream:
        async def stream_response():
            response = agent.chat(user_message, session_id=session_id)
            words = response.split(" ")
            for i, word in enumerate(words):
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": settings.llm_model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": word + (" " if i < len(words) - 1 else "")},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream_response(), media_type="text/event-stream")

    response = agent.chat(user_message, session_id=session_id)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": settings.llm_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── JARVIS endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    stats = agent.stats() if agent else {}
    return {
        "status": "online",
        "agent": settings.agent_name,
        "model": settings.llm_model,
        "platform": settings.jarvis_platform,
        "stats": stats,
    }


@app.post("/ingest/path", dependencies=[Depends(verify_token)])
async def ingest_path(req: IngestRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    result = agent.ingest(req.path)
    log.info("ingest_path", path=req.path)
    return {"result": result}


@app.post("/ingest/upload", dependencies=[Depends(verify_token)])
async def ingest_upload(file: UploadFile = File(...)):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    Path(settings.uploads_path).mkdir(parents=True, exist_ok=True)
    dest = Path(settings.uploads_path) / file.filename
    dest.write_bytes(await file.read())
    result = agent.ingest(str(dest))
    log.info("ingest_upload", filename=file.filename)
    return {"filename": file.filename, "result": result}


@app.post("/ingest/obsidian", dependencies=[Depends(verify_token)])
async def ingest_obsidian(req: ObsidianSyncRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    try:
        results = agent.memory.ingest_obsidian(req.vault_path)
        return results
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/clip", dependencies=[Depends(verify_token)])
async def clip_url(req: ClipRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    try:
        from clipper import clip
        result = clip(req.url, req.tags)
        log.info("clip_url", url=req.url, chunks=result.get("chunks_stored", 0))
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/memory/stats", dependencies=[Depends(verify_token)])
async def memory_stats():
    if not agent:
        raise HTTPException(503, "Agent not ready")
    return agent.stats()


@app.get("/memory/summaries", dependencies=[Depends(verify_token)])
async def memory_summaries():
    if not agent:
        raise HTTPException(503, "Agent not ready")
    return agent.memory.episodic.get_summaries()


@app.post("/plugins", dependencies=[Depends(verify_token)])
async def plugin_action(req: PluginActionRequest):
    """Manage dynamic plugins: request / approve / reject / list."""
    if not agent:
        raise HTTPException(503, "Agent not ready")

    if req.action == "request" and req.request:
        try:
            return agent.plugin_registry.request_plugin(req.request)
        except Exception as e:
            raise HTTPException(500, str(e))

    if req.action == "approve" and req.name:
        result = agent.plugin_registry.approve_plugin(req.name)
        if result.get("status") in ("approved", "already_approved"):
            agent._rebuild_graph()
        return result

    if req.action == "reject" and req.name:
        return agent.plugin_registry.reject_plugin(req.name)

    if req.action == "list":
        return agent.plugin_registry.list_plugins()

    raise HTTPException(400, "Invalid action or missing parameters")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"🤖 {settings.agent_name} API      → http://localhost:{settings.jarvis_port}")
    print(f"📊 Dashboard   → http://localhost:{settings.jarvis_port}/ui/dashboard.html")
    print(f"🔌 Open WebUI  → http://localhost:3000")
    uvicorn.run(
        "main:app",
        host=settings.jarvis_host,
        port=settings.jarvis_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
