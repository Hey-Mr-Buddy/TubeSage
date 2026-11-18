import math
import re
from typing import Dict, List, Set

TOKEN_RE = re.compile(r"[\w']+")
STOP_WORDS = set("a an the is are was were in on at to for of with by".split())


def extract_key_tokens(text: str) -> Set[str]:
    return {
        t.lower()
        for t in TOKEN_RE.findall(text)
        if len(t) > 2 and t.lower() not in STOP_WORDS
    }


def compute_faithfulness(
    answer: str, context_chunks: List[str]
) -> float:
    """
    1. Faithfulness / Groundedness Metric:
       Measures the proportion of substantive claims in the generated answer
       that are directly entailed/supported by the retrieved context chunks.
       
       Mathematical formulation:
         Faithfulness = |{c in AnswerClaims : Context entails c}| / |AnswerClaims|
    """
    if not answer.strip():
        return 0.0
    if not context_chunks:
        return 0.0

    claims = [s.strip() for s in re.split(r"[.!?\n]+", answer) if len(s.strip()) > 10]
    if not claims:
        return 1.0

    context_tokens = set()
    for chunk in context_chunks:
        context_tokens.update(extract_key_tokens(chunk))

    supported_claims = 0
    for claim in claims:
        claim_tokens = extract_key_tokens(claim)
        if not claim_tokens:
            continue
        overlap = len(claim_tokens & context_tokens) / len(claim_tokens)
        if overlap >= 0.65:
            supported_claims += 1

    return round(supported_claims / max(1, len(claims)), 4)


def compute_answer_relevance(
    question: str, answer: str
) -> float:
    """
    2. Answer Relevance Metric:
       Evaluates whether the generated response directly addresses the query
       intent, without topic drift or evasive filler.
    """
    q_tokens = extract_key_tokens(question)
    a_tokens = extract_key_tokens(answer)
    if not q_tokens:
        return 1.0
    if not a_tokens:
        return 0.0

    overlap = len(q_tokens & a_tokens) / len(q_tokens)
    length_penalty = min(1.0, len(a_tokens) / 10.0)
    score = (0.7 * overlap + 0.3 * min(1.0, len(a_tokens) / 20.0)) * length_penalty
    return round(max(0.0, min(1.0, score)), 4)


def compute_context_precision_at_k(
    retrieved_chunk_ids: List[str], ground_truth_relevant_ids: Set[str], k: int = 5
) -> float:
    """
    3. Context Precision@K Metric (Re-ranker Signal-to-Noise Ratio):
       Evaluates whether the highest-ranked chunks are truly relevant.
    """
    if not ground_truth_relevant_ids or not retrieved_chunk_ids:
        return 0.0

    top_k = retrieved_chunk_ids[:k]
    relevant_count = 0
    running_precision_sum = 0.0

    for rank, chunk_id in enumerate(top_k, start=1):
        if chunk_id in ground_truth_relevant_ids:
            relevant_count += 1
            precision_at_rank = relevant_count / rank
            running_precision_sum += precision_at_rank

    total_relevant_possible = min(k, len(ground_truth_relevant_ids))
    if total_relevant_possible == 0:
        return 0.0

    return round(running_precision_sum / total_relevant_possible, 4)


def compute_context_recall(
    ground_truth_statements: List[str], retrieved_chunks: List[str]
) -> float:
    """
    4. Context Recall Metric:
       Validates chunking completeness and coverage for complex multi-hop queries.
    """
    if not ground_truth_statements:
        return 1.0
    if not retrieved_chunks:
        return 0.0

    all_context = " ".join(retrieved_chunks)
    context_tokens = extract_key_tokens(all_context)

    recalled = 0
    for gt in ground_truth_statements:
        gt_tokens = extract_key_tokens(gt)
        if not gt_tokens:
            continue
        overlap = len(gt_tokens & context_tokens) / len(gt_tokens)
        if overlap >= 0.70:
            recalled += 1

    return round(recalled / len(ground_truth_statements), 4)
