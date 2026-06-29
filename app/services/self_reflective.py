from __future__ import annotations

import json

from app.config import settings
from app.models import ReflectionResult
from app.services.llm_service import generate


def reflect_on_answer(question: str, answer: str, context: str) -> ReflectionResult:
    system = (
    "You are an answer quality grader. "
    "Evaluate whether the answer is supported by the context and whether it fully addresses the question. "
    "Return only valid JSON with exactly these keys: "
    "reflection_score, needs_regeneration, refined_question, reasoning. "
    "reflection_score must be a float between 0.0 and 1.0 only. "
    "Use lower scores for unsupported, incomplete, vague, or off-target answers. "
    "Use higher scores only for grounded, complete, and relevant answers. "
    "needs_regeneration must be true or false. "
    "refined_question must be a short improved version of the question when regeneration is needed, otherwise an empty string."
    )

    user = (
    f"Question: {question}\n\n"
    f"Context:\n{context}\n\n"
    f"Answer:\n{answer}\n\n"
    "Remember: reflection_score must be between 0.0 and 1.0."
    )

    result = generate(
        system_prompt=system,
        user_message=user,
        model=settings.llm_model_grader,
        temperature=0.0,
    )
    text = result["text"].strip()

    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()

    data = json.loads(text)

    return ReflectionResult(
        reflection_score=float(data.get("reflection_score", 0.0)),
        needs_regeneration=bool(data.get("needs_regeneration", False)),
        refined_question=str(data.get("refined_question", "")),
        reasoning=str(data.get("reasoning", "")),
    )


def should_regenerate(reflection: ReflectionResult, iterations: int) -> bool:
    if iterations >= settings.max_reflection_retries:
        return False

    if reflection.needs_regeneration:
        return True

    return reflection.reflection_score < settings.reflection_min_score