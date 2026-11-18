import hashlib
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from app.schemas import CitationItem, StructuredAnswer


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Pure-Python high-precision cosine similarity with zero external dependencies."""
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class SemanticVectorCache:
    """
    Two-Tier Query Caching Layer:
      Tier 1: Exact Hash Cache (SHA-256 of video_id:normalized_query) -> <1ms
      Tier 2: Semantic Vector Cache (Cosine similarity >= 0.92) -> ~10-15ms
    
    Technical Rationale for 0.92 Similarity Cutoff:
      - At 0.85, questions with different intents (e.g. "How to install on Windows?" vs
        "How to install on Mac?") trigger false-positive collisions.
      - At >= 0.92, only true paraphrases ("Summarize the main takeaways" vs
        "What are the key points of this video?") collide, preventing hallucination
        and eliminating redundant LLM API costs.
    """

    def __init__(self, similarity_threshold: float = 0.92, ttl_seconds: int = 86400):
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self._exact_cache: Dict[str, Dict[str, Any]] = {}
        self._vector_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _hash_key(self, video_id: str, query: str) -> str:
        clean = " ".join(query.lower().strip().split())
        return hashlib.sha256(f"{video_id}:{clean}".encode("utf-8")).hexdigest()

    def get(
        self, video_id: str, query: str, query_vector: Optional[List[float]] = None
    ) -> Optional[Tuple[StructuredAnswer, str, float]]:
        """
        Attempt cache lookup.
        Returns: Tuple of (StructuredAnswer, hit_type, similarity_score) or None.
        hit_type is 'exact' or 'semantic'.
        """
        now = time.time()
        exact_key = self._hash_key(video_id, query)

        # 1. Tier 1: Exact Hash Match
        if exact_key in self._exact_cache:
            entry = self._exact_cache[exact_key]
            if now - entry["timestamp"] <= self.ttl_seconds:
                entry["hit_count"] += 1
                return entry["answer"], "exact", 1.0
            else:
                del self._exact_cache[exact_key]

        # 2. Tier 2: Semantic Vector Match
        if query_vector and video_id in self._vector_cache:
            best_sim = -1.0
            best_entry = None
            for entry in self._vector_cache[video_id]:
                if now - entry["timestamp"] > self.ttl_seconds:
                    continue
                cached_vec = entry["vector"]
                cos_sim = cosine_similarity(query_vector, cached_vec)
                if cos_sim > best_sim:
                    best_sim = cos_sim
                    best_entry = entry

            if best_entry and best_sim >= self.similarity_threshold:
                best_entry["hit_count"] += 1
                return best_entry["answer"], "semantic", round(best_sim, 4)

        return None

    def put(
        self,
        video_id: str,
        query: str,
        answer: StructuredAnswer,
        query_vector: Optional[List[float]] = None,
    ) -> None:
        """Store query response in exact and semantic vector cache tiers."""
        now = time.time()
        exact_key = self._hash_key(video_id, query)
        payload = {
            "video_id": video_id,
            "query": query,
            "answer": answer,
            "timestamp": now,
            "hit_count": 0,
        }
        self._exact_cache[exact_key] = payload

        if query_vector:
            if video_id not in self._vector_cache:
                self._vector_cache[video_id] = []
            self._vector_cache[video_id].append({
                "query": query,
                "vector": query_vector,
                "answer": answer,
                "timestamp": now,
                "hit_count": 0,
            })

    def invalidate_video(self, video_id: str) -> int:
        """Purge all cached queries associated with a video upon re-indexing."""
        count = 0
        exact_keys_to_del = [
            k for k, v in self._exact_cache.items() if v.get("video_id") == video_id
        ]
        for k in exact_keys_to_del:
            del self._exact_cache[k]
            count += 1

        if video_id in self._vector_cache:
            count += len(self._vector_cache[video_id])
            del self._vector_cache[video_id]

        return count


# Global singleton instance
global_semantic_cache = SemanticVectorCache()
