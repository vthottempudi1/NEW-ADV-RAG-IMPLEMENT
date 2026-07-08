"""
Ragas-compatible metric scorer implemented directly via OpenAI.
Replaces the ragas library dependency to avoid langchain version conflicts.

Metrics implemented:
  - faithfulness:      Are claims in the answer grounded in the retrieved contexts?
  - answer_relevancy:  Does the answer address the question?
  - context_precision: Are the retrieved contexts actually relevant to the question?
  - context_recall:    Does the retrieved context cover the ground-truth answer?
"""
from __future__ import annotations

import json
import re
import statistics
from typing import Any

from openai import OpenAI

from app.config import settings

_client: OpenAI | None = None

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "what",
    "when",
    "which",
}


def _llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _ask(prompt: str) -> str:
    resp = _llm().chat.completions.create(
        model=settings.llm_model_grader,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 2 and token not in _STOPWORDS
    }


def _overlap_score(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


def _score_faithfulness(answer: str, contexts: list[str]) -> float:
    ctx = "\n---\n".join(contexts[:5])
    prompt = f"""Given the following retrieved context and answer, identify each factual claim in the answer.
For each claim, judge whether it is supported by the context (1) or not (0).
Return ONLY a JSON array of 0s and 1s, one per claim. Example: [1, 1, 0, 1]

Context:
{ctx}

Answer:
{answer}

JSON array:"""
    try:
        raw = _ask(prompt)
        scores = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        return statistics.mean(scores) if scores else 0.0
    except Exception:
        return 0.0


def _score_answer_relevancy(question: str, answer: str) -> float:
    prompt = f"""Rate how well the answer addresses the question on a scale from 0.0 to 1.0.
1.0 = fully addresses the question, 0.0 = completely irrelevant or off-topic.
Return ONLY a decimal number between 0.0 and 1.0.

Question: {question}
Answer: {answer}

Score:"""
    try:
        return min(1.0, max(0.0, float(_ask(prompt))))
    except Exception:
        return 0.0


def _score_context_precision(question: str, contexts: list[str]) -> float:
    if not contexts:
        return 0.0
    scores = []
    for ctx in contexts[:5]:
        prompt = f"""Is the following context relevant to answering the question?
Return ONLY 1 (relevant) or 0 (not relevant).

Question: {question}
Context: {ctx[:800]}

Score:"""
        try:
            scores.append(int(_ask(prompt).strip()[0]))
        except Exception:
            scores.append(0)
    # Precision@k with positional weighting
    hits, total = 0, 0
    precision_sum = 0.0
    for i, s in enumerate(scores, 1):
        if s:
            hits += 1
            precision_sum += hits / i
        total += 1
    return (precision_sum / hits) if hits else 0.0


def _score_context_recall(answer: str, contexts: list[str]) -> float:
    ctx = "\n---\n".join(contexts[:5])
    prompt = f"""Given the ground-truth answer and the retrieved contexts, identify each sentence in the ground-truth answer.
For each sentence, judge whether the context supports it (1) or not (0).
Return ONLY a JSON array of 0s and 1s. Example: [1, 0, 1]

Ground-truth answer:
{answer}

Retrieved contexts:
{ctx}

JSON array:"""
    try:
        raw = _ask(prompt)
        scores = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        return statistics.mean(scores) if scores else 0.0
    except Exception:
        return 0.0


def _heuristic_score_faithfulness(answer: str, contexts: list[str]) -> float:
    return round(
        max((_overlap_score(answer, context) for context in contexts), default=0.0),
        3,
    )


def _heuristic_score_answer_relevancy(question: str, answer: str) -> float:
    return round(_overlap_score(question, answer), 3)


def _heuristic_score_context_precision(question: str, contexts: list[str]) -> float:
    if not contexts:
        return 0.0
    scores = [_overlap_score(question, context) for context in contexts]
    return round(sum(scores) / len(scores), 3)


def _heuristic_score_context_recall(answer: str, contexts: list[str]) -> float:
    joined = "\n".join(contexts)
    return round(_overlap_score(answer, joined), 3)


def run(rows: list[dict], scorer: str = "llm") -> list[dict]:
    """Score each row with all four RAGAS metrics. Returns updated rows."""
    if not rows:
        return []
    results = []
    for row in rows:
        q = row.get("question", "")
        ans = row.get("answer", "")
        ctxs = row.get("contexts", [])
        gt = row.get("ground_truth", ans)  # fall back to answer if no ground truth

        if scorer == "heuristic":
            metrics = {
                "faithfulness": _heuristic_score_faithfulness(ans, ctxs),
                "answer_relevancy": _heuristic_score_answer_relevancy(q, ans),
                "context_precision": _heuristic_score_context_precision(q, ctxs),
                "context_recall": _heuristic_score_context_recall(gt, ctxs),
            }
            scoring_backend = "heuristic"
        else:
            metrics = {
                "faithfulness": _score_faithfulness(ans, ctxs),
                "answer_relevancy": _score_answer_relevancy(q, ans),
                "context_precision": _score_context_precision(q, ctxs),
                "context_recall": _score_context_recall(gt, ctxs),
            }

            # If the LLM scorer silently collapses to all-zero metrics for a row
            # with a non-empty answer and contexts, treat that as a scoring failure
            # and fall back to the deterministic heuristic scorer.
            if (
                ans.strip()
                and ctxs
                and all(float(metrics.get(name, 0.0)) == 0.0 for name in (
                    "faithfulness",
                    "answer_relevancy",
                    "context_precision",
                    "context_recall",
                ))
            ):
                metrics = {
                    "faithfulness": _heuristic_score_faithfulness(ans, ctxs),
                    "answer_relevancy": _heuristic_score_answer_relevancy(q, ans),
                    "context_precision": _heuristic_score_context_precision(q, ctxs),
                    "context_recall": _heuristic_score_context_recall(gt, ctxs),
                }
                scoring_backend = "heuristic_fallback"
            else:
                scoring_backend = "llm"

        results.append({
            **row,
            **metrics,
            "scoring_backend": scoring_backend,
        })
    return results






