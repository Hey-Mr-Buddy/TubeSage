from contextlib import contextmanager
import logging
import time
from typing import Dict, Iterator, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("tubesage.observability.tracer")


class LatencyWaterfall(BaseModel):
    ingestion_fetch_ms: float = 0.0
    ingestion_chunk_ms: float = 0.0
    ingestion_embed_ms: float = 0.0
    retrieval_dense_ms: float = 0.0
    retrieval_sparse_ms: float = 0.0
    retrieval_rrf_ms: float = 0.0
    rerank_cross_encoder_ms: float = 0.0
    llm_ttft_ms: float = 0.0
    llm_generation_ms: float = 0.0
    total_request_ms: float = 0.0


class RequestTracer:
    """
    Production Telemetry & Observability Tracer.
    
    Tracks fine-grained latency spans across the end-to-end RAG lifecycle:
      - Media Ingestion Waterfall
      - Dual Retrieval (Dense + Sparse)
      - Rank Fusion & Cross-Encoder Re-Ranking
      - LLM TTFT (Time-to-First-Token) & Total Generation
    """

    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self.spans: Dict[str, float] = {}
        self._active_spans: Dict[str, float] = {}
        self.start_wall_time = time.perf_counter()

    @contextmanager
    def span(self, span_name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.spans[span_name] = duration_ms
            logger.debug("[TRACE %s] span '%s' took %.2f ms", self.trace_id, span_name, duration_ms)

    def record_ttft(self, ttft_ms: float) -> None:
        self.spans["llm_ttft_ms"] = round(ttft_ms, 2)

    def finalize(self) -> LatencyWaterfall:
        total_ms = round((time.perf_counter() - self.start_wall_time) * 1000, 2)
        waterfall = LatencyWaterfall(
            ingestion_fetch_ms=self.spans.get("ingestion_fetch", 0.0),
            ingestion_chunk_ms=self.spans.get("ingestion_chunk", 0.0),
            ingestion_embed_ms=self.spans.get("ingestion_embed", 0.0),
            retrieval_dense_ms=self.spans.get("retrieval_dense", 0.0),
            retrieval_sparse_ms=self.spans.get("retrieval_sparse", 0.0),
            retrieval_rrf_ms=self.spans.get("retrieval_rrf", 0.0),
            rerank_cross_encoder_ms=self.spans.get("rerank_cross_encoder", 0.0),
            llm_ttft_ms=self.spans.get("llm_ttft_ms", 0.0),
            llm_generation_ms=self.spans.get("llm_generation", 0.0),
            total_request_ms=total_ms,
        )
        logger.info(
            "[TRACE %s] Pipeline complete: Total %.1fms | Dense: %.1fms | Sparse: %.1fms | Rerank: %.1fms | TTFT: %.1fms",
            self.trace_id,
            total_ms,
            waterfall.retrieval_dense_ms,
            waterfall.retrieval_sparse_ms,
            waterfall.rerank_cross_encoder_ms,
            waterfall.llm_ttft_ms,
        )
        return waterfall

