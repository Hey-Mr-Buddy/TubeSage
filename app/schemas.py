from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ChapterMarker(BaseModel):
    title: str = Field(description="Title of the YouTube chapter")
    start_seconds: float = Field(ge=0.0, description="Start timestamp of the chapter in seconds")
    end_seconds: Optional[float] = Field(default=None, description="End timestamp of the chapter in seconds")


class TranscriptSnippet(BaseModel):
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    text: str = Field(min_length=1)


class ChunkPayload(BaseModel):
    chunk_id: str = Field(description="Deterministic unique ID (UUIDv5) for the chunk")
    video_id: str = Field(description="11-character YouTube video ID")
    ordinal: int = Field(ge=0, description="0-indexed position within the video chunk sequence")
    start_timestamp: float = Field(ge=0.0, description="Start timestamp in seconds")
    end_timestamp: float = Field(ge=0.0, description="End timestamp in seconds")
    chapter_title: str = Field(default="Overview", description="Associated YouTube chapter marker")
    token_count: int = Field(default=1, ge=0, description="Estimated token count in the chunk")
    text_hash: str = Field(default="", description="SHA-256 hash of the chunk text for cache deduplication")
    text: str = Field(min_length=1, description="Normalized transcript text content")
    embedding: Optional[List[float]] = Field(default=None, description="Dense embedding vector")


class CitationItem(BaseModel):
    claim: str = Field(description="Specific assertion made in the generated answer")
    chunk_id: str = Field(description="ID of the source chunk grounding this claim")
    start_seconds: float = Field(ge=0.0, description="Start timestamp in seconds")
    end_seconds: float = Field(ge=0.0, description="End timestamp in seconds")
    timestamp_label: str = Field(description="Human readable timestamp e.g. '03:45'")
    quote_snippet: str = Field(description="Exact verbatim excerpt from the transcript evidence")
    url: str = Field(description="Deep link URL to YouTube video at start timestamp")


class StructuredAnswer(BaseModel):
    answer: str = Field(description="Comprehensive, grounded answer formatted in Markdown")
    citations: List[CitationItem] = Field(default_factory=list, description="Explicit citations mapping claims to timestamps")
    is_out_of_scope: bool = Field(default=False, description="True if question is outside the video's scope")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Retrieval and grounding confidence score")


class JobStatus(BaseModel):
    job_id: str
    video_id: str
    status: Literal["pending", "downloading", "transcribing", "chunking", "indexing", "ready", "failed"]
    progress_percent: int = Field(ge=0, le=100)
    message: str
    created_at: str
    updated_at: str
    error: Optional[str] = None


class EvalMetricResult(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0, description="Groundedness: fraction of answer claims supported by context")
    answer_relevance: float = Field(ge=0.0, le=1.0, description="Semantic relevance of answer to user query")
    context_precision: float = Field(ge=0.0, le=1.0, description="Re-ranker accuracy: signal-to-noise ratio in top-K")
    context_recall: float = Field(ge=0.0, le=1.0, description="Completeness of retrieved chunks relative to ground truth")
    notes: Dict[str, str] = Field(default_factory=dict)


class LatencyBreakdown(BaseModel):
    cache_lookup_ms: float = 0.0
    embedding_query_ms: float = 0.0
    dense_retrieval_ms: float = 0.0
    sparse_retrieval_ms: float = 0.0
    rrf_fusion_ms: float = 0.0
    cross_encoder_rerank_ms: float = 0.0
    llm_ttft_ms: float = 0.0
    llm_total_ms: float = 0.0
    total_pipeline_ms: float = 0.0

