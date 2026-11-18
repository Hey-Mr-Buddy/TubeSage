from collections import defaultdict, deque
import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import hmac
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.answering import (
    ModelNotConfigured,
    ProviderUnavailable,
    global_answering_service,
)
from app.config import get_settings
from app.database import (
    activate_retrieval_store,
    create_session,
    get_active_video_id,
    get_session,
    get_video,
    init_db,
    load_chunks,
    recent_messages,
    save_evaluation_run,
    save_message,
    session_evaluation_summary,
    video_store_stats,
)
from app.formatting import render_markdown
from app.tasks import global_task_manager
from app.youtube import VideoInputError, parse_video_id, get_video_info
from evals.synthetic_dataset import SyntheticDatasetGenerator

RATE_WINDOW: dict[str, deque[float]] = defaultdict(deque)
logger = logging.getLogger("tubesage.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="TubeSage Enterprise RAG Platform", version="2.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def verify_cloud_identity(request: Request, call_next):
    settings = get_settings()
    if settings.clerk_secret_key and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        timestamp = request.headers.get("X-TubeSage-Timestamp", "")
        user_id = request.headers.get("X-TubeSage-User", "")
        tier = request.headers.get("X-TubeSage-Tier", "")
        thread_id = request.headers.get("X-TubeSage-Thread", "")
        provided = request.headers.get("X-TubeSage-Signature", "")
        try:
            fresh = abs(time.time() - int(timestamp)) <= 60
        except ValueError:
            fresh = False
        canonical = "\n".join([timestamp, request.method.upper(), request.url.path, user_id, tier, thread_id])
        expected = hmac.new(settings.clerk_secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not (fresh and user_id and tier in {"starter", "pro", "enterprise"} and hmac.compare_digest(provided, expected)):
            return JSONResponse(status_code=401, content={"detail": "Trusted application identity required."})
        request.state.user_id, request.state.tier, request.state.thread_id = user_id, tier, thread_id
    return await call_next(request)


class IngestRequest(BaseModel):
    url: str = Field(min_length=3, max_length=500)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=64)
    question: str = Field(min_length=1, max_length=2000)


@app.post("/api/videos/preflight")
def video_preflight(payload: IngestRequest):
    try:
        video_id = parse_video_id(payload.url)
    except VideoInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_video_info(video_id)


def enforce_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    events = RATE_WINDOW[key]
    while events and events[0] < now - 60:
        events.popleft()
    if len(events) >= get_settings().max_chat_messages_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute and retry.")
    events.append(now)


@app.get("/")
def home():
    return FileResponse("app/static/index.html")


@app.get("/api/health")
def health():
    settings = get_settings()
    configured = bool(settings.openai_api_key or settings.gemini_api_key or settings.anthropic_api_key)
    return {
        "status": "healthy",
        "answer_model_configured": configured,
        "primary_provider": "OpenAI" if settings.openai_api_key else "Google Gemini" if settings.gemini_api_key else "Anthropic",
        "primary_model": settings.openai_model if settings.openai_api_key else settings.gemini_model if settings.gemini_api_key else settings.anthropic_model,
        "fallback_provider": "Google Gemini" if settings.openai_api_key and settings.gemini_api_key else "Anthropic" if settings.gemini_api_key and settings.anthropic_api_key else None,
        "fallback_model": settings.gemini_model if settings.openai_api_key and settings.gemini_api_key else settings.anthropic_model if settings.gemini_api_key and settings.anthropic_api_key else None,
        "retrieval_engine": "Hybrid (Dense Vector + BM25Okapi + Cross-Encoder Rerank)",
        "evaluations_enabled": settings.evals_enabled,
    }


@app.post("/api/videos")
async def ingest_video(payload: IngestRequest, request: Request, response: Response):
    try:
        video_id = parse_video_id(payload.url)
    except VideoInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = get_video(video_id)
    thread_id = getattr(request.state, "thread_id", "")
    chunks = load_chunks(video_id)
    if existing and chunks:
        if thread_id and get_settings().cloud_mode:
            from app.supabase_store import save_thread_chunks
            from app.retrieval import DenseRetriever
            dense = DenseRetriever()
            if any(not c.embedding or len(c.embedding) != 1536 for c in chunks):
                vectors = await asyncio.to_thread(dense.get_batch_embeddings, [c.text for c in chunks])
                for chunk, vector in zip(chunks, vectors): chunk.embedding = vector
            await asyncio.to_thread(save_thread_chunks, thread_id, video_id, [c.model_dump() for c in chunks])
        # Self-healing: backfill embeddings for legacy cached chunks if missing
        from app.retrieval import DenseRetriever
        dense = DenseRetriever()
        stale_chunks = (
            chunks
            if not dense.settings.gemini_api_key
            else [c for c in chunks if not c.embedding or len(c.embedding) != dense.expected_dimension]
        )
        if stale_chunks:
            global_task_manager.start_embedding_refresh(
                video_id,
                [c.chunk_id for c in stale_chunks],
                [c.text for c in stale_chunks],
            )

        reset_info = activate_retrieval_store(video_id)
        return {
            "video": {
                "video_id": video_id,
                "url": existing["url"],
                "title": existing["title"],
                "duration_seconds": existing["duration_seconds"],
                "transcript_language": existing["transcript_language"],
                "transcript_generated": bool(existing["transcript_generated"]),
                "store": video_store_stats(video_id),
                "index_reset": reset_info,
            },
            "cached": True,
            "status": "ready",
            "embedding_refresh_pending": bool(stale_chunks),
        }

    # Start immediately and return a ticket; the browser can show live progress
    # while captions, chunking, embeddings, and SQLite indexing run.
    reset_info = activate_retrieval_store(video_id)
    job_id = global_task_manager.create_job(video_id, thread_id)
    global_task_manager.start_ingestion(job_id, video_id, thread_id)
    response.status_code = 202

    return {
        "job_id": job_id,
        "video_id": video_id,
        "status": "pending",
        "progress_percent": 0,
        "message": "Ingestion started",
        "index_reset": reset_info,
    }


@app.get("/api/jobs/{job_id}")
def check_job_status(job_id: str):
    st = global_task_manager.get_status(job_id)
    if not st:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    return st.model_dump()


@app.post("/api/sessions")
def new_session(payload: IngestRequest, request: Request):
    try:
        video_id = parse_video_id(payload.url)
    except VideoInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not get_video(video_id):
        raise HTTPException(status_code=404, detail="Load the video before starting a chat.")
    session_id = getattr(request.state, "thread_id", "") or uuid.uuid4().hex
    create_session(session_id, video_id)
    return {"session_id": session_id, "video_id": video_id}


@app.get("/api/insights/{session_id}")
def session_insights(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {
        "summary": session_evaluation_summary(session_id),
        "store": video_store_stats(session["video_id"]),
        "primary_provider": "Anthropic",
        "primary_configured": bool(get_settings().anthropic_api_key),
        "primary_model": get_settings().anthropic_model,
        "fallback_provider": "Google Gemini" if get_settings().gemini_api_key else None,
        "fallback_model": get_settings().gemini_model if get_settings().gemini_api_key else None,
    }


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request):
    enforce_rate_limit(request)
    session = get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found. Load video first.")
    
    video = get_video(session["video_id"])
    thread_id = getattr(request.state, "thread_id", "")
    if thread_id and payload.session_id != thread_id:
        raise HTTPException(status_code=403, detail="Conversation does not match the signed session.")
    chunks = load_chunks(session["video_id"], thread_id or None)
    if not chunks:
        raise HTTPException(status_code=409, detail="No indexed chunks found for this video. Please reload.")

    history = recent_messages(payload.session_id)
    question = payload.question.strip()

    try:
        result = global_answering_service.generate_answer_sync(question, video, chunks, history, thread_id=thread_id or None)
    except ModelNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Chat generation error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Generation pipeline failed: {str(exc)}") from exc

    save_message(payload.session_id, "user", question)
    save_message(payload.session_id, "assistant", result["answer"], result["citations"])
    save_evaluation_run(
        result["trace"]["run_id"],
        payload.session_id,
        session["video_id"],
        question,
        result["trace"],
    )
    result["answer_html"] = render_markdown(result["answer"])
    return result


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    enforce_rate_limit(request)
    session = get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    video = get_video(session["video_id"])
    thread_id = getattr(request.state, "thread_id", "")
    if thread_id and payload.session_id != thread_id:
        raise HTTPException(status_code=403, detail="Conversation does not match the signed session.")
    chunks = load_chunks(session["video_id"], thread_id or None)
    if not chunks:
        raise HTTPException(status_code=409, detail="No chunks indexed. Reload video.")

    history = recent_messages(payload.session_id)
    question = payload.question.strip()

    return StreamingResponse(
        global_answering_service.stream_answer(question, video, chunks, history, thread_id=thread_id or None),
        media_type="text/event-stream",
    )


@app.get("/api/evals/{video_id}/synthetic")
def generate_synthetic_evals(video_id: str):
    chunks = load_chunks(video_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="Video chunks not found.")
    generator = SyntheticDatasetGenerator()
    triplets = generator.generate_triplets_from_chunks(chunks)
    return {"video_id": video_id, "triplet_count": len(triplets), "triplets": [t.model_dump() for t in triplets]}
