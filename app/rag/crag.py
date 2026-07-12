from __future__ import annotations

import json
from collections.abc import Callable
from statistics import mean

from app.config import settings
from app.models import ChunkRelevance, CRAGEvaluation, RetrievedChunk
from app.rag.llm_service import generate_with_json
from app.rag.web_search import search_web


# Learner note: Encapsulates grade chunks so this responsibility can be understood, tested, and changed independently.
def grade_chunks(question: str, chunks: list[RetrievedChunk]) -> CRAGEvaluation:
    """Perform grade chunks for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if not chunks:
        return CRAGEvaluation(
            relevance_score=0.0,
            relevance_label="irrelevant",
            confidence=1.0,
            reasoning="No chunks retrieved.",
            total_chunk_count=0,
        )

    context = "\n\n".join(
        f"[Source: {chunk.source}]\n{chunk.text}"
        for chunk in chunks[:5]
    )

    system = (
        "You are a strict retrieval-quality evaluator. Score EACH chunk independently against the "
        "user question. A different chunk being useful must not raise another chunk's score. "
        "Return only valid JSON with keys confidence, reasoning, and chunk_evaluations. "
        "chunk_evaluations must contain one object per supplied chunk with keys index, "
        "relevance_score, relevance_label, reasoning. Scores are 0.0 to 1.0 and labels are "
        "highly_relevant, somewhat_relevant, or irrelevant."
    )
    user = (
        f"User Question: {question}\n\n"
        f"Retrieved Context:\n{context}\n\n"
        "Scoring guide for every individual chunk:\n"
        "- 0.0 to 0.3: irrelevant\n"
        "- 0.3 to 0.7: somewhat_relevant\n"
        "- 0.7 to 1.0: highly_relevant\n"
        "Penalize generic topical similarity when the chunk cannot answer the question.\n"
    )

    result = generate_with_json(
        system_prompt=system,
        user_message=user,
        model=settings.llm_model_grader,
        temperature=0.0,
    )
    data = json.loads(result["text"])
    raw_evaluations = data.get("chunk_evaluations")
    evaluations: list[ChunkRelevance] = []
    if isinstance(raw_evaluations, list):
        by_index = {
            int(item.get("index", -1)): item
            for item in raw_evaluations
            if isinstance(item, dict) and str(item.get("index", "")).lstrip("-").isdigit()
        }
        for index, chunk in enumerate(chunks[:5]):
            item = by_index.get(index, {})
            score = min(1.0, max(0.0, float(item.get("relevance_score", 0.0))))
            evaluations.append(
                ChunkRelevance(
                    index=index,
                    source=chunk.source,
                    relevance_score=score,
                    relevance_label=str(item.get("relevance_label", "irrelevant")),
                    reasoning=str(item.get("reasoning", "No per-chunk reasoning returned.")),
                )
            )

    # Preserve compatibility with a grader that temporarily returns the legacy
    # aggregate schema, but make the fallback visible in reasoning and metadata.
    if not evaluations:
        legacy_score = min(1.0, max(0.0, float(data.get("relevance_score", 0.0))))
        evaluations = [
            ChunkRelevance(
                index=index,
                source=chunk.source,
                relevance_score=legacy_score,
                relevance_label=str(data.get("relevance_label", "irrelevant")),
                reasoning="Legacy aggregate grader response; per-chunk score unavailable.",
            )
            for index, chunk in enumerate(chunks[:5])
        ]

    scores = [evaluation.relevance_score for evaluation in evaluations]
    relevant_count = sum(
        score >= settings.crag_chunk_relevance_threshold for score in scores
    )
    relevant_ratio = relevant_count / len(evaluations) if evaluations else 0.0
    aggregate_score = mean(scores) if scores else 0.0
    if (
        aggregate_score >= settings.crag_relevance_threshold
        and relevant_ratio >= settings.crag_min_relevant_ratio
    ):
        aggregate_label = "highly_relevant"
    elif relevant_count:
        aggregate_label = "somewhat_relevant"
    else:
        aggregate_label = "irrelevant"

    return CRAGEvaluation(
        relevance_score=round(aggregate_score, 3),
        relevance_label=aggregate_label,
        confidence=float(data.get("confidence", 0.0)),
        reasoning=str(data.get("reasoning", "")),
        chunk_evaluations=evaluations,
        relevant_chunk_count=relevant_count,
        total_chunk_count=len(evaluations),
        relevant_ratio=round(relevant_ratio, 3),
    )


# Learner Note: Remove chunks CRAG judged irrelevant before answer generation.
def filter_relevant_chunks(
    chunks: list[RetrievedChunk],
    evaluation: CRAGEvaluation,
) -> list[RetrievedChunk]:
    """Keep only chunks meeting the configured evidence-level relevance threshold."""
    relevant_indexes = {
        item.index
        for item in evaluation.chunk_evaluations
        if item.relevance_score >= settings.crag_chunk_relevance_threshold
    }
    return [chunk for index, chunk in enumerate(chunks[:5]) if index in relevant_indexes]


# Learner note: Encapsulates crag pipeline so this responsibility can be understood, tested, and changed independently.
def crag_pipeline(
    question: str,
    chunks: list[RetrievedChunk],
    enable_crag: bool = True,
    local_retry_fn: Callable[[], list[RetrievedChunk]] | None = None,
    allow_web_fallback: bool = True,
) -> tuple[list[RetrievedChunk], CRAGEvaluation, bool]:
    """Perform crag pipeline for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if not enable_crag:
        return (
            chunks,
            CRAGEvaluation(
                relevance_score=1.0,
                relevance_label="disabled",
                confidence=1.0,
                reasoning="CRAG disabled.",
            ),
            False,
        )

    evaluation = grade_chunks(question, chunks)

    filtered_chunks = filter_relevant_chunks(chunks, evaluation)
    if (
        evaluation.relevance_score >= settings.crag_relevance_threshold
        and evaluation.relevant_ratio >= settings.crag_min_relevant_ratio
    ):
        return filtered_chunks, evaluation, False

    if local_retry_fn is not None:
        retried_chunks = local_retry_fn()
        retry_eval = grade_chunks(question, retried_chunks)
        retry_filtered = filter_relevant_chunks(retried_chunks, retry_eval)
        if (
            retry_eval.relevant_ratio,
            retry_eval.relevance_score,
        ) > (
            evaluation.relevant_ratio,
            evaluation.relevance_score,
        ):
            filtered_chunks = retry_filtered
            evaluation = retry_eval

    if allow_web_fallback and evaluation.relevance_score < settings.crag_ambiguous_threshold:
        try:
            web_chunks = search_web(question)
            if web_chunks:
                web_evaluation = grade_chunks(question, web_chunks)
                web_filtered = filter_relevant_chunks(web_chunks, web_evaluation)
                if web_filtered:
                    return web_filtered, web_evaluation, True
        except ValueError:
            pass

    return filtered_chunks, evaluation, False
