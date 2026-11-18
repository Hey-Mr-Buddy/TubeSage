import hashlib
import json
import logging
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.schemas import ChunkPayload

logger = logging.getLogger("tubesage.retrieval")
ANTHROPIC_EMBEDDING_MODEL = "claude-sonnet-5-5"
ANTHROPIC_HTTP_TIMEOUT_MS = 12_000

TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
# Minimal grammar-only stopwords so semantic words like 'about', 'video', 'explain', 'tell', 'summarize' are NOT stripped
STOP_WORDS = set(
    "a an the is are was were in on at to for of with by from and or so it its that this these those be been".split()
)

BROAD_QUERY_PATTERNS = [
    "what is this video about",
    "what is the video about",
    "what's this video about",
    "what's the video about",
    "what is this about",
    "what does this video",
    "summar",
    "overview",
    "key point",
    "main idea",
    "main point",
    "takeaway",
    "whole video",
    "entire video",
    "explain the video",
    "tell me about",
    "what happened",
    "who is",
    "core topic",
    "give me a summary",
    "what is discussed",
]


def is_broad_query(query: str) -> bool:
    """Detect if the user is asking an overarching summary/overview question about the entire video."""
    normalized = query.lower().strip()
    return any(p in normalized for p in BROAD_QUERY_PATTERNS)


def tokenize(text: str) -> List[str]:
    """Tokenize text into lower-cased keywords with intelligent fallback if all words are stop words."""
    words = [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1]
    filtered = [w for w in words if w not in STOP_WORDS]
    # If filtering eliminated all tokens, fall back to unfiltered words
    return filtered if filtered else words


class BM25Retriever:
    """
    Sparse Lexical Search via BM25Okapi.
    
    Hyperparameters:
      - k1: 1.2 (controls non-linear term frequency saturation)
      - b: 0.75 (document length penalization ratio)
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def score(
        self, query: str, chunks: List[ChunkPayload]
    ) -> List[Tuple[ChunkPayload, float]]:
        query_terms = tokenize(query)
        if not query_terms or not chunks:
            return []

        docs = [tokenize(c.text) for c in chunks]
        avg_len = sum(map(len, docs)) / max(1, len(docs))
        df = Counter(term for doc in docs for term in set(doc))
        n_docs = len(docs)

        scored_chunks: List[Tuple[ChunkPayload, float]] = []
        for chunk, doc in zip(chunks, docs):
            tf = Counter(doc)
            score = 0.0
            doc_len = len(doc)
            for term in set(query_terms):
                frequency = tf[term]
                if not frequency:
                    continue
                idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                numerator = frequency * (self.k1 + 1.0)
                denominator = frequency + self.k1 * (1.0 - self.b + self.b * (doc_len / max(1.0, avg_len)))
                score += idf * (numerator / denominator)

            query_phrase = " ".join(query_terms)
            doc_text = " ".join(doc)
            if query_phrase and query_phrase in doc_text:
                score += 2.5

            if score > 0:
                scored_chunks.append((chunk, score))

        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks


class DenseRetriever:
    """
    Dense Semantic Search.

    Uses normalized Anthropic text embeddings with cosine similarity. If Anthropic is
    unavailable or unconfigured, a stable local hash projection keeps the store usable.
    """

    def __init__(self):
        self.settings = get_settings()

    def _anthropic_client(self):
        import anthropic
        return anthropic.Anthropic(api_key=self.settings.anthropic_api_key, timeout=ANTHROPIC_HTTP_TIMEOUT_MS / 1000)

    @property
    def expected_dimension(self) -> int:
        return 1536 if self.settings.cloud_mode or self.settings.anthropic_api_key else 128

    def _anthropic_embeddings(self, texts: List[str]) -> List[List[float]]:
        client = self._anthropic_client()
        response = client.messages.create(
            model=self.settings.anthropic_embedding_model,
            input=texts,
            embedding_type="float",
        )
        return [e.embedding for e in response.embeddings]

    def get_query_embedding(self, query: str) -> List[float]:
        if self.settings.anthropic_api_key:
            try:
                return self._anthropic_embeddings([query])[0]
            except Exception:
                logger.exception("Anthropic query embedding failed; using deterministic local fallback")

        return self._fallback_pseudo_embedding(query, 1536 if self.settings.cloud_mode else 128)

    def get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.settings.anthropic_api_key:
            try:
                return self._anthropic_embeddings(texts)
            except Exception:
                logger.exception("Anthropic batch embeddings failed; using deterministic local fallback")

        return [self._fallback_pseudo_embedding(t, 1536 if self.settings.cloud_mode else 128) for t in texts]

    def _fallback_pseudo_embedding(self, text: str, dim: int = 128) -> List[float]:
        """Deterministic 128-d normalized hash-projected embedding."""
        vec = [0.0] * dim
        words = tokenize(text)
        for w in words:
            digest = hashlib.blake2b(w.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest, "big") % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def score(
        self, query_vec: List[float], chunks: List[ChunkPayload]
    ) -> List[Tuple[ChunkPayload, float]]:
        if not chunks or not query_vec:
            return []
        q_norm = math.sqrt(sum(x * x for x in query_vec))
        if q_norm == 0:
            return []

        scored: List[Tuple[ChunkPayload, float]] = []
        for c in chunks:
            # Self-healing: if chunk has no embedding, generate on the fly
            if not c.embedding:
                c.embedding = self._fallback_pseudo_embedding(c.text)

            # Do not compare vectors from incompatible embedding models/dimensions.
            if len(c.embedding) != len(query_vec):
                continue

            d_norm = math.sqrt(sum(x * x for x in c.embedding))
            if d_norm == 0:
                continue
            dot = sum(a * b for a, b in zip(query_vec, c.embedding))
            cos_sim = dot / (q_norm * d_norm)
            scored.append((c, cos_sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


class CrossEncoderReranker:
    """
    Second-Stage Re-Ranking Engine.
    
    Evaluates (Query, Candidate Passage) pairs using joint cross-attention
    to produce calibrated semantic relevance scores.
    Prunes Top-N candidates down to Top-K highest-precision passages.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model = None
        self._init_attempted = False

    def _lazy_init(self):
        if not self._init_attempted:
            self._init_attempted = True
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name)
            except Exception:
                self._model = None

    def rerank(
        self, query: str, candidates: List[ChunkPayload], top_k: int = 5
    ) -> List[Tuple[ChunkPayload, float]]:
        if not candidates:
            return []

        self._lazy_init()
        if self._model is not None:
            pairs = [[query, c.text] for c in candidates]
            scores = self._model.predict(pairs)
            scored = list(zip(candidates, [float(s) for s in scores]))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

        # Resilient Cross-Encoder fallback: semantic similarity + rank decay
        q_terms = set(tokenize(query))
        scored = []
        for rank, c in enumerate(candidates):
            c_terms = tokenize(c.text)
            overlap = len(q_terms & set(c_terms)) / max(1, len(q_terms)) if q_terms else 0.5
            phrase_bonus = 0.3 if query.lower() in c.text.lower() else 0.0
            rank_prior = 1.0 / (1.0 + 0.1 * rank)
            calibrated_score = 0.4 * overlap + phrase_bonus + 0.4 * rank_prior
            scored.append((c, round(calibrated_score, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def reciprocal_rank_fusion(
    dense_ranks: List[Tuple[ChunkPayload, float]],
    sparse_ranks: List[Tuple[ChunkPayload, float]],
    k_constant: int = 60,
    w_dense: float = 0.60,
    w_sparse: float = 0.40,
    candidate_limit: int = 25,
) -> List[Tuple[ChunkPayload, float]]:
    rrf_scores: Dict[str, float] = {}
    chunk_map: Dict[str, ChunkPayload] = {}

    for rank_idx, (chunk, _) in enumerate(dense_ranks, start=1):
        c_id = chunk.chunk_id
        chunk_map[c_id] = chunk
        rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (w_dense / (k_constant + rank_idx))

    for rank_idx, (chunk, _) in enumerate(sparse_ranks, start=1):
        c_id = chunk.chunk_id
        chunk_map[c_id] = chunk
        rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (w_sparse / (k_constant + rank_idx))

    sorted_results = sorted(
        [(chunk_map[cid], score) for cid, score in rrf_scores.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    return sorted_results[:candidate_limit]


class HybridRetrievalEngine:
    """
    Multi-Stage Hybrid Retrieval Engine:
      Stage 1: Intent check (Broad summary queries vs Specific queries)
      Stage 2: Concurrent Dense Semantic + Sparse BM25 Search
      Stage 3: Reciprocal Rank Fusion (RRF) -> Top-25 Candidates
      Stage 4: Cross-Encoder Re-Ranking -> Top-5 Precision Candidates
      Stage 5: Confidence Gating
    """

    def __init__(
        self,
        rrf_k: int = 60,
        w_dense: float = 0.60,
        w_sparse: float = 0.40,
        top_n_candidates: int = 25,
        top_k_final: int = 5,
        confidence_cutoff: float = 0.05,
    ):
        self.sparse_retriever = BM25Retriever(k1=1.2, b=0.75)
        self.dense_retriever = DenseRetriever()
        self.reranker = CrossEncoderReranker()
        self.rrf_k = rrf_k
        self.w_dense = w_dense
        self.w_sparse = w_sparse
        self.top_n_candidates = top_n_candidates
        self.top_k_final = top_k_final
        self.confidence_cutoff = confidence_cutoff

    def retrieve(
        self,
        query: str,
        chunks: List[ChunkPayload],
        query_vector: Optional[List[float]] = None,
        thread_id: Optional[str] = None,
    ) -> Tuple[List[Tuple[ChunkPayload, float]], bool, float]:
        """
        Execute full multi-stage hybrid retrieval.
        """
        if not chunks or not query.strip():
            return [], True, 0.0

        # Special Stage: Broad / Overview Query Handling
        # If the user asks for a video summary or overarching question, retrieve evenly distributed chunks
        if is_broad_query(query):
            count = min(self.top_k_final, len(chunks))
            if count <= len(chunks):
                indices = sorted({round(i * (len(chunks) - 1) / max(1, count - 1)) for i in range(count)})
            else:
                indices = list(range(len(chunks)))
            selected = [(chunks[idx], 1.0) for idx in indices]
            return selected, False, 1.0

        # Ensure all chunks have embeddings
        for c in chunks:
            if not c.embedding:
                c.embedding = self.dense_retriever._fallback_pseudo_embedding(c.text)

        # Stage 1: Dual Retrieval
        sparse_scored = self.sparse_retriever.score(query, chunks)
        if query_vector is None:
            query_vector = self.dense_retriever.get_query_embedding(query)
        if thread_id and get_settings().cloud_mode:
            try:
                from app.supabase_store import match_thread_chunks
                matches = match_thread_chunks(thread_id, chunks[0].video_id, query_vector, self.top_n_candidates)
                rank_by_id = {row.get("chunk_id"): float(row.get("similarity", 0)) for row in matches}
                dense_scored = [(c, rank_by_id[c.chunk_id]) for c in chunks if c.chunk_id in rank_by_id]
                dense_scored.sort(key=lambda item: item[1], reverse=True)
            except Exception:
                logger.exception("Supabase vector retrieval failed; using local dense index")
                dense_scored = self.dense_retriever.score(query_vector, chunks)
        else:
            dense_scored = self.dense_retriever.score(query_vector, chunks)

        # Stage 2: Reciprocal Rank Fusion (RRF)
        fused_candidates = reciprocal_rank_fusion(
            dense_ranks=dense_scored,
            sparse_ranks=sparse_scored,
            k_constant=self.rrf_k,
            w_dense=self.w_dense,
            w_sparse=self.w_sparse,
            candidate_limit=self.top_n_candidates,
        )

        if not fused_candidates and chunks:
            # Fallback if both sparse and dense were low: select top 3 chunks
            fused_candidates = [(c, 0.1) for c in chunks[:3]]

        candidate_chunks = [item[0] for item in fused_candidates]

        # Stage 3: Cross-Encoder Re-Ranking
        final_ranked = self.reranker.rerank(
            query=query,
            candidates=candidate_chunks,
            top_k=self.top_k_final,
        )

        top_score = final_ranked[0][1] if final_ranked else 0.0
        confidence = max(0.0, min(1.0, top_score))

        # Only consider out-of-scope if there are zero candidates or confidence is strictly zero
        is_out_of_scope = len(final_ranked) == 0 or confidence < self.confidence_cutoff

        return final_ranked, is_out_of_scope, round(confidence, 4)
