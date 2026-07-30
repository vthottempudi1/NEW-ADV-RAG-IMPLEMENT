from __future__ import annotations

import json

from app.config import settings
from app.models import ReflectionResult
from app.rag.llm_service import generate_with_json


def reflect_on_answer(question: str, answer: str, context: str) -> ReflectionResult:
    """Use the grader LLM to critique a generated answer against the question and context.

    Sends a strict-reviewer prompt asking the grader model to score the answer
    on relevance, accuracy, completeness, and clarity, and to flag whether it
    needs regeneration (e.g. because it hedges, refuses, misses parts of the
    question, or invents facts). Parses the JSON response into a
    `ReflectionResult` with `reflection_score`, `needs_regeneration`,
    `refined_question`, and `reasoning`, applying safe defaults for any
    missing keys.
    """
    system = (
        "You are a strict reviewer evaluating an AI-generated answer. "
        "Fail answers that hedge, refuse, miss major parts of the question, or invent facts. "
        "Return only valid JSON with exactly these keys: reflection_score, needs_regeneration, "
        "refined_question, reasoning. reflection_score must be a float between 0.0 and 1.0."
    )

    user = (
        f"User Question: {question}\n\n"
        f"Generated Answer: {answer}\n\n"
        f"Retrieved Context: {context}\n\n"
        "Evaluate these criteria strictly: relevance, accuracy, completeness, clarity. "
        "needs_regeneration should be true if the answer is vague, unsupported, incomplete, or if a sharper "
        "reformulation of the question would improve retrieval. "
        "When needs_regeneration is true, refined_question must be a single improved question."
    )

    result = generate_with_json(
        system_prompt=system,
        user_message=user,
        model=settings.llm_model_grader,
        temperature=0.0,
    )
    data = json.loads(result["text"])

    return ReflectionResult(
        reflection_score=float(data.get("reflection_score", 0.0)),
        needs_regeneration=bool(data.get("needs_regeneration", False)),
        refined_question=str(data.get("refined_question", "")),
        reasoning=str(data.get("reasoning", "")),
    )


def should_regenerate(reflection: ReflectionResult, iterations: int) -> bool:
    """Decide whether the self-reflective loop should regenerate the answer.

    Always returns False once `iterations` has reached the configured retry
    limit (`settings.max_reflection_retries`), regardless of the reflection
    outcome. Otherwise returns True if the reflection explicitly flagged
    `needs_regeneration`, or if the reflection score falls below the
    configured minimum (`settings.reflection_min_score`).
    """
    if iterations >= settings.max_reflection_retries:
        return False

    if reflection.needs_regeneration:
        return True

    return reflection.reflection_score < settings.reflection_min_score
