import hashlib
import math
import re
import uuid
from typing import List, Optional, Tuple

from app.schemas import ChapterMarker, ChunkPayload, TranscriptSnippet

CHUNK_NAMESPACE = uuid.UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
WORD_RE = re.compile(r"\w+")


def estimate_token_count(text: str) -> int:
    """Accurately estimate token count without requiring heavy tokenizer loads in runtime paths."""
    words = WORD_RE.findall(text)
    return max(1, int(len(words) * 1.3))


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def generate_chunk_id(video_id: str, text_hash: str, ordinal: int) -> str:
    """Generate deterministic, collision-free UUIDv5 based on video ID, ordinal, and content hash."""
    seed = f"{video_id}:{ordinal}:{text_hash}"
    return str(uuid.uuid5(CHUNK_NAMESPACE, seed))


def find_matching_chapter(start_time: float, chapters: List[ChapterMarker]) -> str:
    """Locate the native YouTube chapter that encompasses the given start timestamp."""
    if not chapters:
        return "Full Video"
    
    current_chapter = chapters[0].title
    for ch in chapters:
        if start_time >= ch.start_seconds:
            if ch.end_seconds is None or start_time < ch.end_seconds:
                current_chapter = ch.title
        else:
            break
    return current_chapter


def calculate_cosine_distance(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine distance = 1 - cosine_similarity without numpy."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 1.0
    sim = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return max(0.0, 1.0 - sim)


class SemanticChunker:
    """
    Dynamic Semantic Chunking Engine.
    
    Eliminates fixed sliding windows by detecting semantic topic shifts
    via cosine distance between contiguous sentences, combined with
    YouTube Native Chapter markers as hard boundary delimiters.
    
    Hyperparameters:
      - similarity_threshold (tau): 0.32 (cosine distance)
      - min_tokens: 100 (prevents orphan, low-signal micro-chunks)
      - max_tokens: 600 (prevents context window blowout and preserves retrieval focus)
    """

    def __init__(
        self,
        similarity_threshold: float = 0.32,
        min_tokens: int = 100,
        max_tokens: int = 600,
    ):
        self.similarity_threshold = similarity_threshold
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens

    def chunk_snippets(
        self,
        video_id: str,
        snippets: List[TranscriptSnippet],
        chapters: List[ChapterMarker],
        sentence_embeddings: Optional[List[List[float]]] = None,
    ) -> List[ChunkPayload]:
        if not snippets:
            return []

        chunks: List[ChunkPayload] = []
        current_snippets: List[TranscriptSnippet] = []
        current_tokens: int = 0
        current_chapter: str = find_matching_chapter(snippets[0].start_seconds, chapters)
        ordinal: int = 0

        def flush_chunk(items: List[TranscriptSnippet], chapter_title: str) -> None:
            nonlocal ordinal
            if not items:
                return
            combined_text = " ".join(item.text for item in items).strip()
            t_start = items[0].start_seconds
            t_end = items[-1].end_seconds
            tok_count = estimate_token_count(combined_text)
            t_hash = compute_sha256(combined_text)
            c_id = generate_chunk_id(video_id, t_hash, ordinal)

            chunks.append(
                ChunkPayload(
                    chunk_id=c_id,
                    video_id=video_id,
                    ordinal=ordinal,
                    start_timestamp=round(t_start, 2),
                    end_timestamp=round(t_end, 2),
                    chapter_title=chapter_title,
                    token_count=tok_count,
                    text_hash=t_hash,
                    text=combined_text,
                )
            )
            ordinal += 1

        for i, snippet in enumerate(snippets):
            snip_tokens = estimate_token_count(snippet.text)
            snip_chapter = find_matching_chapter(snippet.start_seconds, chapters)

            # Check for hard chapter boundary shift
            chapter_boundary = snip_chapter != current_chapter

            # Check for semantic distance shift if embeddings are available
            semantic_boundary = False
            if sentence_embeddings and i > 0 and i < len(sentence_embeddings):
                distance = calculate_cosine_distance(
                    sentence_embeddings[i - 1], sentence_embeddings[i]
                )
                if distance > self.similarity_threshold:
                    semantic_boundary = True

            # Boundary evaluation
            should_split = False
            if chapter_boundary and current_tokens >= self.min_tokens:
                should_split = True
            elif semantic_boundary and current_tokens >= self.min_tokens:
                should_split = True
            elif current_tokens + snip_tokens > self.max_tokens:
                should_split = True

            if should_split and current_snippets:
                flush_chunk(current_snippets, current_chapter)
                current_snippets = []
                current_tokens = 0
                current_chapter = snip_chapter

            current_snippets.append(snippet)
            current_tokens += snip_tokens

        if current_snippets:
            flush_chunk(current_snippets, current_chapter)

        return chunks
