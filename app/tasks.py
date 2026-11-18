import asyncio
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Set
import uuid

from app.chunking import SemanticChunker
from app.database import activate_retrieval_store, get_video, save_reindexed_video, save_video
from app.retrieval import DenseRetriever
from app.schemas import JobStatus
from app.youtube import fetch_transcript_resilient, get_metadata

logger = logging.getLogger("tubesage.tasks")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionTaskManager:
    """
    Decoupled Asynchronous Ingestion Task Worker.
    
    Manages long-running ingestion jobs with real-time status updates:
      PENDING -> DOWNLOADING -> TRANSCRIBING -> CHUNKING -> INDEXING -> READY (or FAILED)
    """

    def __init__(self):
        self._jobs: Dict[str, JobStatus] = {}
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._maintenance_tasks: Set[asyncio.Task] = set()
        self._dense_retriever = DenseRetriever()
        self._chunker = SemanticChunker(similarity_threshold=0.32, min_tokens=100, max_tokens=600)

    def create_job(self, video_id: str, thread_id: str = "") -> str:
        job_id = uuid.uuid4().hex
        self._jobs[job_id] = JobStatus(
            job_id=job_id,
            video_id=video_id,
            status="pending",
            progress_percent=0,
            message="Job queued for processing",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        return job_id

    def get_status(self, job_id: str) -> Optional[JobStatus]:
        return self._jobs.get(job_id)

    def start_ingestion(self, job_id: str, video_id: str, thread_id: str = "") -> None:
        """Start ingestion before returning the job ticket so the client can poll progress."""
        task = asyncio.create_task(self.execute_ingestion(job_id, video_id, thread_id))
        self._running_tasks[job_id] = task
        task.add_done_callback(lambda _task: self._running_tasks.pop(job_id, None))

    def start_embedding_refresh(self, video_id: str, chunk_ids: List[str], texts: List[str]) -> None:
        """Refresh stale cached vectors without holding up the Load response."""
        task = asyncio.create_task(self._refresh_embeddings(video_id, chunk_ids, texts))
        self._maintenance_tasks.add(task)
        task.add_done_callback(self._maintenance_tasks.discard)

    async def _refresh_embeddings(self, video_id: str, chunk_ids: List[str], texts: List[str]) -> None:
        try:
            embeddings = await asyncio.to_thread(self._dense_retriever.get_batch_embeddings, texts)
            from app.database import save_chunk_embeddings
            await asyncio.to_thread(save_chunk_embeddings, video_id, chunk_ids, embeddings)
            logger.info("Refreshed %d cached embeddings for video %s", len(embeddings), video_id)
        except Exception:
            logger.exception("Could not refresh cached embeddings for video %s", video_id)

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress_percent: int,
        message: str,
        error: Optional[str] = None,
    ) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = status  # type: ignore
            job.progress_percent = progress_percent
            job.message = message
            job.updated_at = now_iso()
            if error:
                job.error = error
            logger.info("Job %s [%s%%] %s: %s", job_id, progress_percent, status, message)

            # Broadcast to any active WebSocket listeners
            if job_id in self._subscribers:
                for q in list(self._subscribers[job_id]):
                    await q.put(job.model_dump())

    def subscribe(self, job_id: str) -> asyncio.Queue:
        if job_id not in self._subscribers:
            self._subscribers[job_id] = set()
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id].add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        if job_id in self._subscribers and q in self._subscribers[job_id]:
            self._subscribers[job_id].remove(q)

    async def execute_ingestion(self, job_id: str, video_id: str, thread_id: str = "") -> None:
        """Background asynchronous execution pipeline."""
        try:
            # Step 1: Downloading metadata
            await self.update_status(job_id, "downloading", 15, "Fetching video metadata and chapters")
            title, chapters = get_metadata(video_id)

            # Step 2: Transcribing / Caption retrieval
            await self.update_status(job_id, "transcribing", 40, "Retrieving resilient caption track (Manual -> Auto -> Whisper)")
            # Execute synchronous caption retrieval in threadpool to prevent event loop blocking
            snippets, language, is_generated = await asyncio.to_thread(
                fetch_transcript_resilient, video_id
            )

            # Step 3: Chunking
            await self.update_status(job_id, "chunking", 65, "Splitting captions at chapter and token boundaries")
            chunks = self._chunker.chunk_snippets(
                video_id=video_id,
                snippets=snippets,
                chapters=chapters,
                sentence_embeddings=None,
            )

            # Step 4: Indexing & Embeddings
            await self.update_status(job_id, "indexing", 85, "Generating dense vectors and BM25 index")
            chunk_texts = [c.text for c in chunks]
            embeddings = await asyncio.to_thread(
                self._dense_retriever.get_batch_embeddings, chunk_texts
            )
            for c, emb in zip(chunks, embeddings):
                c.embedding = emb

            # Save to database
            duration = max(item.end_seconds for item in snippets)
            record = {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": title,
                "transcript_language": language,
                "transcript_generated": is_generated,
                "duration_seconds": duration,
                "transcript_text": " ".join(item.text for item in snippets),
            }

            raw_chunks = [c.model_dump() for c in chunks]
            if thread_id:
                from app.supabase_store import save_thread_chunks
                await asyncio.to_thread(save_thread_chunks, thread_id, video_id, raw_chunks)
            existing = get_video(video_id)
            if existing:
                save_reindexed_video(record, raw_chunks)
            else:
                save_video(record, raw_chunks)

            activate_retrieval_store(video_id)
            await self.update_status(job_id, "ready", 100, f"Successfully indexed {len(chunks)} semantic chunks")

        except Exception as exc:
            logger.exception("Ingestion failed for job %s: %s", job_id, exc)
            await self.update_status(job_id, "failed", 0, "Ingestion failed", error=str(exc))


# Global Task Manager Singleton
global_task_manager = IngestionTaskManager()

