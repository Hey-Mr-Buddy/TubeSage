"""Small server-side PostgREST adapter for thread-scoped SaaS persistence."""
import httpx

from app.config import get_settings


def _request(method: str, table: str, *, params=None, json=None, headers=None):
    settings = get_settings()
    if not settings.cloud_mode:
        raise RuntimeError("Supabase cloud storage is not configured")
    base = settings.supabase_url.rstrip("/") + "/rest/v1/"
    common = {"apikey": settings.supabase_service_role_key,
              "Authorization": f"Bearer {settings.supabase_service_role_key}",
              "Content-Type": "application/json"}
    common.update(headers or {})
    response = httpx.request(method, base + table, params=params, json=json, headers=common, timeout=30)
    response.raise_for_status()
    return response.json() if response.content else None


def save_thread_chunks(thread_id: str, video_id: str, chunks: list[dict]):
    if not chunks:
        return
    # Replace the thread's vectors atomically enough for idempotent ingestion.
    _request("DELETE", "vector_embeddings", params={"thread_id": f"eq.{thread_id}", "video_id": f"eq.{video_id}"})
    rows = []
    for chunk in chunks:
        vector = chunk.get("embedding")
        if not vector or len(vector) != 1536:
            continue
        rows.append({"thread_id": thread_id, "video_id": video_id,
                     "chunk_id": chunk["chunk_id"], "ordinal": chunk["ordinal"],
                     "start_seconds": chunk.get("start_timestamp", 0),
                     "end_seconds": chunk.get("end_timestamp", 0),
                     "chapter_title": chunk.get("chapter_title", "Overview"),
                     "token_count": chunk.get("token_count", 0),
                     "text_hash": chunk.get("text_hash", ""), "content": chunk["text"],
                     "embedding": vector})
    if rows:
        _request("POST", "vector_embeddings", json=rows, headers={"Prefer": "resolution=merge-duplicates"})


def load_thread_chunks(thread_id: str, video_id: str):
    rows = _request("GET", "vector_embeddings", params={
        "select": "chunk_id,video_id,ordinal,start_seconds,end_seconds,chapter_title,token_count,text_hash,content,embedding",
        "thread_id": f"eq.{thread_id}", "video_id": f"eq.{video_id}", "order": "ordinal.asc"})
    result = []
    for row in rows or []:
        raw = row.get("embedding")
        vector = [float(x) for x in raw.strip("[]").split(",")] if isinstance(raw, str) else raw
        result.append({"chunk_id": row["chunk_id"], "video_id": row["video_id"], "ordinal": row["ordinal"],
                       "start_timestamp": row["start_seconds"], "end_timestamp": row["end_seconds"],
                       "chapter_title": row["chapter_title"], "token_count": row["token_count"],
                       "text_hash": row["text_hash"], "text": row["content"], "embedding": vector})
    return result


def match_thread_chunks(thread_id: str, video_id: str, embedding: list[float], count: int = 25):
    result = _request("POST", "rpc/match_thread_embeddings", json={
        "query_embedding": embedding, "match_thread_id": thread_id,
        "match_video_id": video_id, "match_count": count})
    return result or []


def save_cloud_message(thread_id: str, role: str, content: str, citations=None):
    _request("POST", "chat_messages", json={"thread_id": thread_id, "role": role,
        "content": content, "citations": citations or []}, headers={"Prefer": "return=minimal"})
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    _request("PATCH", "chat_threads", params={"id": f"eq.{thread_id}"},
        json={"updated_at": now, "last_message_at": now}, headers={"Prefer": "return=minimal"})


def load_cloud_messages(thread_id: str, limit: int = 8):
    return _request("GET", "chat_messages", params={"select": "role,content", "thread_id": f"eq.{thread_id}",
        "order": "created_at.desc", "limit": str(limit)}) or []


def save_cloud_eval(run_id: str, thread_id: str, video_id: str, question: str, trace: dict):
    _request("POST", "evaluation_runs", json={"run_id": run_id, "thread_id": thread_id,
        "video_id": video_id, "question": question, "trace": trace}, headers={"Prefer": "return=minimal"})


def load_cloud_evaluations(thread_id: str, limit: int = 50):
    return _request("GET", "evaluation_runs", params={"select": "trace,created_at", "thread_id": f"eq.{thread_id}",
        "order": "created_at.desc", "limit": str(limit)}) or []
