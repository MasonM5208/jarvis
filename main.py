"""
JARVIS API Server (FastAPI)
---------------------------
Runs on http://localhost:8000
Endpoints are OpenAI-compatible so Open WebUI connects with zero config.

Start with: python main.py
"""
import os
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import uuid
import time
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.settings import LLM_MODEL, AGENT_NAME, UPLOADS_PATH
from agent.agent import JarvisAgent
from pathlib import Path


# ── App lifecycle ─────────────────────────────────────────────────────────────

agent: Optional[JarvisAgent] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    print("🚀 Starting JARVIS...")
    agent = JarvisAgent()
    yield
    print("👋 JARVIS shutting down.")

app = FastAPI(title="JARVIS", version="1.0.0", lifespan=lifespan)
app.mount("/ui", StaticFiles(directory="interface", html=True), name="ui")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ─────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = LLM_MODEL
    messages: list[Message]
    stream: bool = False
    session_id: Optional[str] = None

class IngestRequest(BaseModel):
    path: str

class BriefRequest(BaseModel):
    speak: bool = False   # if True, also speak via TTS (hotkey uses this)


# ── Slash command router ──────────────────────────────────────────────────────

def _handle_slash(command: str, session_id: str) -> Optional[str]:
    """
    Intercept /commands before they hit the LLM.
    Returns a response string, or None to pass through to the agent.
    """
    cmd = command.strip().lower()

    if cmd in ("/brief", "/briefing"):
        from briefing import generate_briefing
        return generate_briefing(agent)

    if cmd == "/stats":
        s = agent.stats()
        return (
            f"**JARVIS Memory Stats**\n"
            f"- Knowledge chunks: {s['knowledge_chunks']}\n"
            f"- Long-term summaries: {s['summaries']}"
        )

    if cmd == "/help":
        return (
            "**JARVIS Commands**\n"
            "- `/brief` — generate your daily briefing\n"
            "- `/stats` — show memory stats\n"
            "- `/help` — show this message\n"
            "- `ingest <path>` — feed a file or folder into memory\n\n"
            "Or just chat naturally — JARVIS will use tools as needed."
        )

    return None   # not a slash command


# ── OpenAI-compatible endpoints ───────────────────────────────────────────────

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": LLM_MODEL, "object": "model", "owned_by": AGENT_NAME}]
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")

    user_message = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )
    session_id = req.session_id or str(uuid.uuid4())

    # Check for slash commands first
    if user_message.startswith("/"):
        slash_response = _handle_slash(user_message, session_id)
        if slash_response is not None:
            def _wrap(text):
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": LLM_MODEL,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            if req.stream:
                async def _stream_slash():
                    words = slash_response.split(" ")
                    for i, word in enumerate(words):
                        chunk = {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": LLM_MODEL,
                            "choices": [{"index": 0, "delta": {"content": word + (" " if i < len(words)-1 else "")}, "finish_reason": None}]
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_stream_slash(), media_type="text/event-stream")
            return _wrap(slash_response)

    if req.stream:
        async def stream_response():
            response = agent.chat(user_message, session_id=session_id)
            words = response.split(" ")
            for i, word in enumerate(words):
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": LLM_MODEL,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": word + (" " if i < len(words) - 1 else "")},
                        "finish_reason": None,
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    response = agent.chat(user_message, session_id=session_id)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": LLM_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── JARVIS-specific endpoints ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "online", "agent": AGENT_NAME, "stats": agent.stats() if agent else {}}


@app.post("/brief")
async def daily_brief(req: BriefRequest = BriefRequest()):
    """Generate a daily briefing. Optionally speak it via TTS."""
    if not agent:
        raise HTTPException(503, "Agent not ready")
    from briefing import generate_briefing, format_briefing_for_speech
    briefing = generate_briefing(agent)
    if req.speak:
        try:
            from voice import get_voice
            v = get_voice()
            v.speak(format_briefing_for_speech(briefing))
        except Exception:
            pass
    return {"briefing": briefing}


@app.post("/ingest/path")
async def ingest_path(req: IngestRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    result = agent.ingest(req.path)
    return {"result": result}


@app.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    Path(UPLOADS_PATH).mkdir(parents=True, exist_ok=True)
    dest = Path(UPLOADS_PATH) / file.filename
    dest.write_bytes(await file.read())
    result = agent.ingest(str(dest))
    return {"filename": file.filename, "result": result}


@app.get("/memory/stats")
async def memory_stats():
    if not agent:
        raise HTTPException(503, "Agent not ready")
    return agent.stats()


@app.get("/memory/summaries")
async def memory_summaries():
    if not agent:
        raise HTTPException(503, "Agent not ready")
    return agent.episodic.get_summaries()




# ── GA feedback endpoints ─────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    session_id: str
    positive: bool

@app.post("/feedback")
async def record_feedback(req: FeedbackRequest):
    from ga.logger import ga_logger
    updated = ga_logger.record_feedback(req.session_id, req.positive)
    return {"updated": updated}

@app.get("/ga/logs")
async def ga_logs(limit: int = 50):
    from ga.logger import ga_logger
    return ga_logger.get_recent(limit)

@app.post("/tts/toggle")
async def tts_toggle(enabled: bool):
    """Toggle TTS on or off at runtime."""
    try:
        from voice import get_voice
        v = get_voice()
        v.set_tts(enabled)
        return {"tts_enabled": enabled}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Clip endpoint ─────────────────────────────────────────────────────────────

class ClipRequest(BaseModel):
    url: str
    tags: list[str] = []

@app.post("/clip")
async def clip_url(req: ClipRequest):
    if not agent:
        raise HTTPException(503, "Agent not ready")
    try:
        from clipper import clip
        result = clip(req.url, req.tags)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"🤖 {AGENT_NAME} API starting on http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
