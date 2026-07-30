from __future__ import annotations

import json
from collections.abc import Callable
from statistics import mean

from app.config import settings
from app.models import ChunkRelevance, CRAGEvaluation, RetrievedChunk
from app.rag.llm_service import generate_with_json
from app.rag.web_search import search_web


def grade_chunks(question: str, chunks: list[RetrievedChunk]) -> CRAGEvaluation:
    """Score up to the first 5 retrieved chunks for relevance to the question using the grader LLM.

    Sends all chunks in a single JSON-mode call and asks for an independent
    per-chunk score/label/reasoning so one strong chunk cannot inflate another's
    score. If the model returns the expected `chunk_evaluations` list, those
    per-chunk scores are used directly; if it instead returns the legacy
    aggregate-only schema (just `relevance_score`/`relevance_label`), that single
    score is applied to every chunk as a fallback so callers keep working.

    The aggregate result is derived from the per-chunk scores: a chunk counts as
    "relevant" if its score meets `crag_chunk_relevance_threshold`, and the
    overall label is "highly_relevant" only when both the mean score meets
    `crag_relevance_threshold` and the relevant ratio meets
    `crag_min_relevant_ratio`; otherwise it's "somewhat_relevant" if any chunk
    qualified, else "irrelevant".

    Returns a CRAGEvaluation with relevance_label="irrelevant" and
    total_chunk_count=0 immediately if no chunks were supplied (no LLM call is made).
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
    (
        f"[Chunk {index}]\n"
        f"[Source: {chunk.source}]\n"
        f"[Authority tier: "
        f"{(chunk.metadata or {}).get('authority_tier', 'unknown')}]\n"
        f"{chunk.text}"
    )
    for index, chunk in enumerate(chunks[:5]))

    system = (
    "You are a strict retrieval-quality evaluator for a Kubernetes "
    "operations knowledge base. Score EACH chunk independently against "
    "the user question. Topical similarity alone is insufficient. "
    "Prefer authority_tier=true Kubernetes documentation and "
    "authority_tier=uploaded enterprise documents. Strongly penalize "
    "authority_tier=noisy when the chunk is generic research rather "
    "than evidence that can answer the Kubernetes question. "
    "A useful chunk elsewhere must not raise another chunk's score. "
    "Return only valid JSON with keys confidence, reasoning, and "
    "chunk_evaluations. chunk_evaluations must contain one object per "
    "supplied chunk with keys index, relevance_score, relevance_label, "
    "and reasoning. Scores are between 0.0 and 1.0. Labels must be "
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


def crag_pipeline(
    question: str,
    chunks: list[RetrievedChunk],
    enable_crag: bool = True,
    local_retry_fn: Callable[[], list[RetrievedChunk]] | None = None,
    allow_web_fallback: bool = True,
) -> tuple[list[RetrievedChunk], CRAGEvaluation, bool]:
    """Run the Corrective RAG (CRAG) grade-retry-fallback flow over retrieved chunks.

    If enable_crag is False, returns the input chunks unfiltered with a synthetic
    "disabled" evaluation. Otherwise it grades the chunks with grade_chunks and,
    if the aggregate relevance/ratio already clears the configured thresholds,
    returns the filtered chunks immediately (used_web_fallback=False).

    If the initial grade is insufficient and local_retry_fn is provided, it is
    called to fetch an alternative local chunk set; that retry is only adopted
    if its (relevant_ratio, relevance_score) improves on the original. If the
    (possibly retried) score is still below crag_ambiguous_threshold and
    allow_web_fallback is True, falls back to a live web search (search_web) and
    grades those results too, adopting them only if the web-filtered set is
    non-empty; a ValueError from the web search is swallowed and treated as no
    fallback available.

    Returns a (filtered_chunks, evaluation, used_web_fallback) tuple.
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
