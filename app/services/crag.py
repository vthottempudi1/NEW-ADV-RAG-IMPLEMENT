from __future__ import annotations

import json
from collections.abc import Callable

from app.config import settings
from app.models import CRAGEvaluation, RetrievedChunk
from app.services.llm_service import generate_with_json
from app.services.web_search import search_web


def grade_chunks(question: str, chunks: list[RetrievedChunk]) -> CRAGEvaluation:
    if not chunks:
        return CRAGEvaluation(
            relevance_score=0.0,
            relevance_label="irrelevant",
            confidence=1.0,
            reasoning="No chunks retrieved.",
        )

    context = "\n\n".join(
        f"[Source: {chunk.source}]\n{chunk.text}"
        for chunk in chunks[:5]
    )

    system = (
        "You are evaluating whether retrieved documents are relevant to answering a user question. "
        "Be strict and grounded. Return only valid JSON with keys: relevance_score, relevance_label, "
        "confidence, reasoning. relevance_score must be between 0.0 and 1.0. "
        "Use only these labels: highly_relevant, somewhat_relevant, irrelevant."
    )
    user = (
        f"User Question: {question}\n\n"
        f"Retrieved Context:\n{context}\n\n"
        "Scoring guide:\n"
        "- 0.0 to 0.3: irrelevant\n"
        "- 0.3 to 0.7: somewhat_relevant\n"
        "- 0.7 to 1.0: highly_relevant\n"
    )

    result = generate_with_json(
        system_prompt=system,
        user_message=user,
        model=settings.llm_model_grader,
        temperature=0.0,
    )
    data = json.loads(result["text"])
    return CRAGEvaluation(
        relevance_score=float(data.get("relevance_score", 0.0)),
        relevance_label=str(data.get("relevance_label", "")),
        confidence=float(data.get("confidence", 0.0)),
        reasoning=str(data.get("reasoning", "")),
    )


def crag_pipeline(
    question: str,
    chunks: list[RetrievedChunk],
    enable_crag: bool = True,
    local_retry_fn: Callable[[], list[RetrievedChunk]] | None = None,
    allow_web_fallback: bool = True,
) -> tuple[list[RetrievedChunk], CRAGEvaluation, bool]:
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

    if evaluation.relevance_score >= settings.crag_relevance_threshold:
        return chunks, evaluation, False

    if (
        evaluation.relevance_score >= settings.crag_ambiguous_threshold
        and local_retry_fn is not None
    ):
        retried_chunks = local_retry_fn()
        retry_eval = grade_chunks(question, retried_chunks)
        if retry_eval.relevance_score > evaluation.relevance_score:
            return retried_chunks, retry_eval, False

    if allow_web_fallback and evaluation.relevance_score < settings.crag_ambiguous_threshold:
        try:
            web_chunks = search_web(question)
            if web_chunks:
                return web_chunks, evaluation, True
        except ValueError:
            pass

    return chunks, evaluation, False
