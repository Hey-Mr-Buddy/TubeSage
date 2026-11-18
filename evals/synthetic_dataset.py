import json
import logging
import random
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas import ChunkPayload

logger = logging.getLogger("tubesage.evals.synthetic")


class EvaluationTriplet(BaseModel):
    query_id: str
    query_type: str = Field(description="factoid | multi_hop | out_of_scope")
    question: str
    ground_truth_context_chunk_ids: List[str]
    ground_truth_answer: str
    chapter_source: str


SYNTHETIC_GENERATION_PROMPT = """You are a Staff Evaluation Architect generating offline benchmark datasets for a YouTube RAG system.
Given the transcript passages below from a video, generate high-quality evaluation triplets.

Passages:
{passages}

Output JSON format:
{{
  "triplets": [
    {{
      "query_type": "factoid",
      "question": "Specific question about a concrete detail in passage 1",
      "ground_truth_context_chunk_ids": ["{chunk_id_1}"],
      "ground_truth_answer": "Precise answer directly verified by passage 1"
    }},
    {{
      "query_type": "multi_hop",
      "question": "Reasoning question connecting information across passages",
      "ground_truth_context_chunk_ids": ["{chunk_id_1}", "{chunk_id_2}"],
      "ground_truth_answer": "Synthesized factual answer using both passages"
    }},
    {{
      "query_type": "out_of_scope",
      "question": "A plausible-sounding question on a related subject that is NOT covered in these passages",
      "ground_truth_context_chunk_ids": [],
      "ground_truth_answer": "The provided video transcript does not cover this topic."
    }}
  ]
}}
"""


class SyntheticDatasetGenerator:
    """
    Offline Ground Truth Generation Pipeline.
    
    Generates synthetic benchmark datasets for RAG offline evaluation
    (Ragas / DeepEval format). Samples video transcript chunks stratified
    across chapters to test factoid retrieval, multi-hop reasoning, and
    out-of-scope refusal handling.
    """

    def __init__(self):
        self.settings = get_settings()

    def generate_triplets_from_chunks(
        self,
        chunks: List[ChunkPayload],
        sample_size: int = 6,
    ) -> List[EvaluationTriplet]:
        if not chunks:
            return []

        # Stratified sampling across chapters
        by_chapter: Dict[str, List[ChunkPayload]] = {}
        for c in chunks:
            by_chapter.setdefault(c.chapter_title, []).append(c)

        sampled_chunks: List[ChunkPayload] = []
        for ch_title, ch_chunks in by_chapter.items():
            sampled_chunks.extend(random.sample(ch_chunks, min(2, len(ch_chunks))))

        if len(sampled_chunks) > sample_size:
            sampled_chunks = random.sample(sampled_chunks, sample_size)

        passages_text = "\n\n".join(
            f"Chunk ID: {c.chunk_id}\nChapter: {c.chapter_title}\nTimestamp: {c.start_timestamp}s - {c.end_timestamp}s\nContent: {c.text}"
            for c in sampled_chunks
        )

        c1 = sampled_chunks[0].chunk_id
        c2 = sampled_chunks[1].chunk_id if len(sampled_chunks) > 1 else c1
        prompt = SYNTHETIC_GENERATION_PROMPT.format(
            passages=passages_text,
            chunk_id_1=c1,
            chunk_id_2=c2,
        )

        # Call Gemini or Anthropic
        triplets: List[EvaluationTriplet] = []
        try:
            if self.settings.gemini_api_key:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.settings.gemini_api_key)
                resp = client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3,
                    ),
                )
                data = json.loads(resp.text or "{}")
                for i, item in enumerate(data.get("triplets", [])):
                    triplets.append(
                        EvaluationTriplet(
                            query_id=f"syn_{i + 1}",
                            query_type=item.get("query_type", "factoid"),
                            question=item.get("question", ""),
                            ground_truth_context_chunk_ids=item.get("ground_truth_context_chunk_ids", []),
                            ground_truth_answer=item.get("ground_truth_answer", ""),
                            chapter_source=sampled_chunks[0].chapter_title,
                        )
                    )
        except Exception as exc:
            logger.warning("LLM synthetic dataset generation fallback invoked: %s", exc)

        # Fallback deterministic synthetic triplets if API is offline
        if not triplets:
            for i, chunk in enumerate(sampled_chunks[:3]):
                words = chunk.text.split()
                snippet = " ".join(words[:6])
                triplets.append(
                    EvaluationTriplet(
                        query_id=f"fallback_{i + 1}",
                        query_type="factoid",
                        question=f"What does the speaker explain regarding {snippet}?",
                        ground_truth_context_chunk_ids=[chunk.chunk_id],
                        ground_truth_answer=chunk.text[:150] + "...",
                        chapter_source=chunk.chapter_title,
                    )
                )

        return triplets

    def export_ragas_format(
        self, triplets: List[EvaluationTriplet], file_path: str
    ) -> None:
        """Export dataset to JSONL format compatible with Ragas / DeepEval benchmarks."""
        rows = []
        for t in triplets:
            rows.append({
                "user_input": t.question,
                "reference_contexts": t.ground_truth_context_chunk_ids,
                "reference_answer": t.ground_truth_answer,
                "metadata": {
                    "query_id": t.query_id,
                    "query_type": t.query_type,
                    "chapter_source": t.chapter_source,
                },
            })
        with open(file_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        logger.info("Exported %d evaluation triplets to %s", len(rows), file_path)

