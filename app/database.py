import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from app.config import get_settings
from app.schemas import ChunkPayload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(get_settings().db_path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
            transcript_language TEXT NOT NULL, transcript_generated INTEGER NOT NULL,
            duration_seconds REAL NOT NULL, transcript_text TEXT NOT NULL, ingested_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT UNIQUE,
            video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            chapter_title TEXT NOT NULL DEFAULT 'Overview',
            token_count INTEGER NOT NULL DEFAULT 0,
            text_hash TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            embedding_json TEXT DEFAULT NULL,
            UNIQUE(video_id, ordinal)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id, ordinal);
        
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
        
        CREATE TABLE IF NOT EXISTS evaluation_runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_eval_session ON evaluation_runs(session_id, created_at);
        
        CREATE TABLE IF NOT EXISTS active_retrieval_store (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            video_id TEXT NOT NULL,
            activated_at TEXT NOT NULL
        );
        """)

        # Migration helper: ensure new columns exist if table was previously created with older schema
        cols = [r["name"] for r in db.execute("PRAGMA table_info(chunks)").fetchall()]
        if "chunk_id" not in cols:
            db.execute("ALTER TABLE chunks ADD COLUMN chunk_id TEXT")
        if "chapter_title" not in cols:
            db.execute("ALTER TABLE chunks ADD COLUMN chapter_title TEXT NOT NULL DEFAULT 'Overview'")
        if "token_count" not in cols:
            db.execute("ALTER TABLE chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
        if "text_hash" not in cols:
            db.execute("ALTER TABLE chunks ADD COLUMN text_hash TEXT NOT NULL DEFAULT ''")
        if "embedding_json" not in cols:
            db.execute("ALTER TABLE chunks ADD COLUMN embedding_json TEXT DEFAULT NULL")
            
        # Create index after column migration is guaranteed
        db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(text_hash)")


def get_video(video_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        return dict(row) if row else None


def save_video(video: dict, chunks: list[dict]) -> None:
    with connect() as db:
        db.execute("DELETE FROM videos WHERE video_id=?", (video["video_id"],))
        db.execute("""INSERT INTO videos(video_id,url,title,transcript_language,transcript_generated,
            duration_seconds,transcript_text,ingested_at) VALUES(?,?,?,?,?,?,?,?)""",
            (video["video_id"], video["url"], video["title"], video["transcript_language"],
             int(video["transcript_generated"]), video["duration_seconds"], video["transcript_text"], now_iso()))
        
        for c in chunks:
            emb_json = json.dumps(c.get("embedding")) if c.get("embedding") and not get_settings().cloud_mode else None
            db.execute("""INSERT INTO chunks(
                chunk_id, video_id, ordinal, start_seconds, end_seconds,
                chapter_title, token_count, text_hash, text, embedding_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (c.get("chunk_id", f"{video['video_id']}:{c['ordinal']}"),
             video["video_id"], c["ordinal"], c.get("start_timestamp", c.get("start_seconds", 0.0)),
             c.get("end_timestamp", c.get("end_seconds", 0.0)),
             c.get("chapter_title", "Overview"), c.get("token_count", 0),
             c.get("text_hash", ""), c["text"], emb_json))


def save_reindexed_video(video: dict, chunks: list[dict]) -> None:
    with connect() as db:
        db.execute("""UPDATE videos SET url=?,title=?,transcript_language=?,transcript_generated=?,
            duration_seconds=?,transcript_text=?,ingested_at=? WHERE video_id=?""",
            (video["url"], video["title"], video["transcript_language"], int(video["transcript_generated"]),
             video["duration_seconds"], video["transcript_text"], now_iso(), video["video_id"]))
        
        db.execute("DELETE FROM chunks WHERE video_id=?", (video["video_id"],))
        for c in chunks:
            emb_json = json.dumps(c.get("embedding")) if c.get("embedding") and not get_settings().cloud_mode else None
            db.execute("""INSERT INTO chunks(
                chunk_id, video_id, ordinal, start_seconds, end_seconds,
                chapter_title, token_count, text_hash, text, embedding_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (c.get("chunk_id", f"{video['video_id']}:{c['ordinal']}"),
             video["video_id"], c["ordinal"], c.get("start_timestamp", c.get("start_seconds", 0.0)),
             c.get("end_timestamp", c.get("end_seconds", 0.0)),
             c.get("chapter_title", "Overview"), c.get("token_count", 0),
             c.get("text_hash", ""), c["text"], emb_json))


def load_chunks(video_id: str, thread_id: str | None = None) -> List[ChunkPayload]:
    if thread_id and get_settings().cloud_mode:
        from app.supabase_store import load_thread_chunks
        return [ChunkPayload(**row) for row in load_thread_chunks(thread_id, video_id)]
    with connect() as db:
        rows = db.execute(
            """SELECT chunk_id, video_id, ordinal, start_seconds, end_seconds,
                      chapter_title, token_count, text_hash, text, embedding_json
               FROM chunks WHERE video_id=? ORDER BY ordinal""", (video_id,)
        ).fetchall()
        
        results: List[ChunkPayload] = []
        for r in rows:
            emb = json.loads(r["embedding_json"]) if r["embedding_json"] else None
            tok_count = r["token_count"] or 0
            if tok_count < 1:
                tok_count = max(1, int(len(r["text"].split()) * 1.3))
            t_hash = r["text_hash"] or ""
            results.append(
                ChunkPayload(
                    chunk_id=r["chunk_id"] or f"{r['video_id']}:{r['ordinal']}",
                    video_id=r["video_id"],
                    ordinal=r["ordinal"],
                    start_timestamp=r["start_seconds"],
                    end_timestamp=r["end_seconds"],
                    chapter_title=r["chapter_title"] or "Overview",
                    token_count=tok_count,
                    text_hash=t_hash,
                    text=r["text"],
                    embedding=emb,
                )
            )
        return results


def save_chunk_embeddings(video_id: str, chunk_ids: List[str], embeddings: List[List[float]]) -> None:
    """Persist a batch only for chunks that still belong to this video."""
    with connect() as db:
        db.executemany(
            "UPDATE chunks SET embedding_json=? WHERE video_id=? AND chunk_id=?",
            [(json.dumps(vector), video_id, chunk_id) for chunk_id, vector in zip(chunk_ids, embeddings)],
        )


def get_active_video_id() -> str | None:
    with connect() as db:
        row = db.execute("SELECT video_id FROM active_retrieval_store WHERE singleton=1").fetchone()
        return row["video_id"] if row else None


def activate_retrieval_store(video_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT video_id FROM active_retrieval_store WHERE singleton=1").fetchone()
        previous = row["video_id"] if row else None
        switched = previous != video_id
        # Keep the active retrieval/vector store scoped to exactly one video.
        # Video/session/evaluation metadata remains cached; old transcript chunks
        # are re-created if that video is loaded again later.
        # In local mode retain the original single-active-vector-store behavior.
        # Cloud mode stores vectors per thread in Supabase and shares this local
        # transcript cache among requests, so deleting other cached chunks would
        # break concurrent users and repeat expensive transcript ingestion.
        removed = 0
        if not get_settings().cloud_mode:
            deleted = db.execute("DELETE FROM chunks WHERE video_id<>?", (video_id,))
            removed = deleted.rowcount
        if switched:
            db.execute("""INSERT INTO active_retrieval_store(singleton,video_id,activated_at) VALUES(1,?,?)
                ON CONFLICT(singleton) DO UPDATE SET video_id=excluded.video_id, activated_at=excluded.activated_at""",
                (video_id, now_iso()))
        return {"reset": switched, "previous_video_id": previous, "removed_chunks": removed}


def video_store_stats(video_id: str) -> dict:
    with connect() as db:
        video = db.execute("SELECT transcript_language,transcript_generated FROM videos WHERE video_id=?", (video_id,)).fetchone()
        chunks = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(text)),0) AS chars, COUNT(embedding_json) AS vecs FROM chunks WHERE video_id=?", (video_id,)).fetchone()
        messages = db.execute("SELECT COUNT(*) AS n FROM messages WHERE session_id IN (SELECT session_id FROM sessions WHERE video_id=?)", (video_id,)).fetchone()
        active_row = db.execute("SELECT video_id FROM active_retrieval_store WHERE singleton=1").fetchone()
        db_path = get_settings().db_path
        db_size = sum(path.stat().st_size for path in (
            db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")
        ) if path.exists())
        return {
            "backend": "SQLite (Hybrid WAL Store)",
            "retrieval_index": "BM25 + Dense Vector RRF",
            "vector_index": "Active (Cosine Similarity)",
            "active_video": bool(active_row and active_row["video_id"] == video_id),
            "embedding_count": chunks["vecs"] if chunks else 0,
            "chunk_count": chunks["n"] if chunks else 0,
            "transcript_chars": chunks["chars"] if chunks else 0,
            "database_bytes": db_size,
            "chat_message_count": messages["n"] if messages else 0,
            "transcript_language": video["transcript_language"] if video else None,
            "captions_auto_generated": bool(video["transcript_generated"]) if video else None,
        }


def save_evaluation_run(run_id: str, session_id: str, video_id: str, question: str, trace: dict) -> None:
    if get_settings().cloud_mode:
        from app.supabase_store import save_cloud_eval
        save_cloud_eval(run_id, session_id, video_id, question, trace)
        return
    with connect() as db:
        db.execute("INSERT INTO evaluation_runs(run_id,session_id,video_id,question,trace_json,created_at) VALUES(?,?,?,?,?,?)",
            (run_id, session_id, video_id, question, json.dumps(trace), now_iso()))


def session_evaluation_summary(session_id: str) -> dict:
    if get_settings().cloud_mode:
        from app.supabase_store import load_cloud_evaluations
        rows = load_cloud_evaluations(session_id)
        traces = [(row.get("trace", {}), row.get("created_at", "")) for row in rows]
        judged = [trace["llm_evaluation"] for trace, _ in traces if trace.get("llm_evaluation", {}).get("status") == "complete"]
        averages = {}
        for metric in ("faithfulness", "answer_relevance", "context_precision", "context_recall", "groundedness", "citation_precision"):
            values = [item.get("scores", {}).get(metric) for item in judged]
            values = [value for value in values if isinstance(value, (int, float))]
            averages[metric] = round(sum(values) / len(values), 1) if values else None
        pipelines = [trace.get("pipeline", {}) for trace, _ in traces]
        generations = [trace.get("generation", {}) for trace, _ in traces]
        total = [p.get("total_ms") or p.get("total_pipeline_ms") or 0 for p in pipelines]
        averages["total_ms"] = round(sum(total) / len(total)) if total else 0
        for key in ("input_tokens", "output_tokens"):
            values = [g.get(key, 0) for g in generations if g.get(key)]
            averages[key] = round(sum(values) / len(values)) if values else 0
        return {"run_count": len(traces), "judged_run_count": len(judged), "averages": averages,
            "recent_runs": [{"run_id": trace.get("run_id"), "created_at": at,
                "scores": trace.get("llm_evaluation", {}).get("scores"),
                "status": trace.get("llm_evaluation", {}).get("status", "not_run")} for trace, at in traces[:12]]}
    with connect() as db:
        rows = db.execute("SELECT trace_json,created_at FROM evaluation_runs WHERE session_id=? ORDER BY created_at DESC LIMIT 50", (session_id,)).fetchall()
        traces = [(json.loads(row["trace_json"]), row["created_at"]) for row in rows]
        judged = [trace["llm_evaluation"] for trace, _ in traces if trace.get("llm_evaluation", {}).get("status") == "complete"]
        averages = {}
        for metric in ("faithfulness", "answer_relevance", "context_precision", "context_recall", "groundedness", "citation_precision"):
            values = [evaluation.get("scores", {}).get(metric) for evaluation in judged]
            values = [value for value in values if isinstance(value, (int, float))]
            averages[metric] = round(sum(values) / len(values), 1) if values else None

        pipelines = [trace.get("pipeline", {}) for trace, _ in traces]
        generations = [trace.get("generation", {}) for trace, _ in traces]

        # Robust extraction of total latency ms
        total_times = [
            item.get("total_ms") or item.get("total_pipeline_ms") or 0
            for item in pipelines
            if (item.get("total_ms") or item.get("total_pipeline_ms"))
        ]
        averages["total_ms"] = round(sum(total_times) / len(total_times)) if total_times else 0

        input_toks = [item.get("input_tokens") or 0 for item in generations if item.get("input_tokens")]
        output_toks = [item.get("output_tokens") or 0 for item in generations if item.get("output_tokens")]
        averages["input_tokens"] = round(sum(input_toks) / len(input_toks)) if input_toks else 0
        averages["output_tokens"] = round(sum(output_toks) / len(output_toks)) if output_toks else 0

        return {
            "run_count": len(traces),
            "judged_run_count": len(judged),
            "averages": averages,
            "recent_runs": [
                {
                    "run_id": trace.get("run_id"),
                    "created_at": created_at,
                    "scores": trace.get("llm_evaluation", {}).get("scores"),
                    "status": trace.get("llm_evaluation", {}).get("status", "not_run"),
                }
                for trace, created_at in traces[:12]
            ],
        }


def create_session(session_id: str, video_id: str) -> None:
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO sessions(session_id,video_id,created_at) VALUES(?,?,?)", (session_id, video_id, now_iso()))


def get_session(session_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None


def recent_messages(session_id: str, limit: int = 8) -> list[dict]:
    if get_settings().cloud_mode:
        from app.supabase_store import load_cloud_messages
        return list(reversed(load_cloud_messages(session_id, limit)))
    with connect() as db:
        rows = db.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]


def save_message(session_id: str, role: str, content: str, citations: list[dict] | None = None) -> None:
    if get_settings().cloud_mode:
        from app.supabase_store import save_cloud_message
        save_cloud_message(session_id, role, content, citations)
        return
    with connect() as db:
        db.execute("INSERT INTO messages(session_id,role,content,citations,created_at) VALUES(?,?,?,?,?)",
            (session_id, role, content, json.dumps(citations or []), now_iso()))
