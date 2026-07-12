from __future__ import annotations

import json

from app.config import settings
from app.models import ReflectionResult
from app.rag.llm_service import generate_with_json


# Learner note: Encapsulates reflect on answer so this responsibility can be understood, tested, and changed independently.
def reflect_on_answer(question: str, answer: str, context: str) -> ReflectionResult:
    """Perform reflect on answer for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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


# Learner note: Evaluates should regenerate as a guardrail before later pipeline stages proceed.
def should_regenerate(reflection: ReflectionResult, iterations: int) -> bool:
    """Perform should regenerate for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if iterations >= settings.max_reflection_retries:
        return False

    if reflection.needs_regeneration:
        return True

    return reflection.reflection_score < settings.reflection_min_score
