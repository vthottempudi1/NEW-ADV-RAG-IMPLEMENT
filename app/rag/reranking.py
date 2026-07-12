from __future__ import annotations

import re
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.config import settings
from app.models import RetrievedChunk


# Learner Note: Loading a cross-encoder is expensive, so each worker reuses one model instance.
@lru_cache(maxsize=2)
def _get_cross_encoder(model_name: str) -> CrossEncoder:
    """Load and cache a reranker model once per worker process and model name.

    Architecture Role:
        Prevents every API request from reloading the same transformer weights.
    Why Important:
        Repeated model construction increases latency, memory churn, and the risk
        that an evaluation or production worker times out under sequential load.
    """
    return CrossEncoder(model_name)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "last",
    "many",
    "month",
    "of",
    "on",
    "or",
    "our",
    "say",
    "the",
    "this",
    "to",
    "was",
    "what",
    "were",
    "with",
}
_TROUBLESHOOTING_HINTS = {
    "error",
    "fix",
    "troubleshoot",
    "troubleshooting",
    "debug",
    "debugging",
    "runbook",
    "incident",
    "oomkilled",
    "errimagepull",
    "imagepullbackoff",
    "crashloopbackoff",
    "logs",
}
_TROUBLESHOOTING_SOURCE_HINTS = {
    "runbook",
    "troubleshooting",
    "incident",
    "eviction",
    "debug",
    "log",
}
_TERM_EXPANSIONS = {
    "errimagepull": {"imagepullbackoff", "image", "pull", "registry"},
    "imagepullbackoff": {"errimagepull", "image", "pull", "registry"},
    "oomkilled": {"oom", "killed", "memory", "eviction"},
    "crashloopbackoff": {"crash", "loop", "backoff", "restart", "logs"},
}


# Learner note: Encapsulates normalize so this responsibility can be understood, tested, and changed independently.
def _normalize(values: list[float]) -> list[float]:
    """Support the retrieval-augmented generation pipeline by performing normalize.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not values:
        return []

    low = min(values)
    high = max(values)

    if high == low:
        return [1.0 for _ in values]

    scale = high - low
    return [(value - low) / scale for value in values]


# Learner note: Encapsulates keyword overlap so this responsibility can be understood, tested, and changed independently.
def _keyword_overlap(query: str, chunk: RetrievedChunk) -> float:
    """Support the retrieval-augmented generation pipeline by performing keyword overlap.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    query_terms = _query_terms(query)
    if not query_terms:
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:400]}".lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return matched / len(query_terms)


# Learner note: Encapsulates query terms so this responsibility can be understood, tested, and changed independently.
def _query_terms(query: str) -> set[str]:
    """Support the retrieval-augmented generation pipeline by performing query terms.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_./:-]+", query):
        lowered = token.lower()
        if len(lowered) >= 2 and lowered not in _STOPWORDS:
            terms.add(lowered)

        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", token):
            lowered_part = part.lower()
            if len(lowered_part) >= 2 and lowered_part not in _STOPWORDS:
                terms.add(lowered_part)

        terms.update(_TERM_EXPANSIONS.get(lowered, set()))

    return terms


# Learner note: Encapsulates is troubleshooting query so this responsibility can be understood, tested, and changed independently.
def _is_troubleshooting_query(query: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is troubleshooting query.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = query.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    for token in re.findall(r"[A-Za-z0-9_./:-]+", query):
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


# Learner note: Encapsulates exact token bonus so this responsibility can be understood, tested, and changed independently.
def _exact_token_bonus(query: str, chunk: RetrievedChunk) -> float:
    """Support the retrieval-augmented generation pipeline by performing exact token bonus.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not _is_troubleshooting_query(query):
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:800]}".lower()
    bonus = 0.0
    exact_terms = {term for term in _query_terms(query) if len(term) >= 4}
    matched = sum(1 for term in exact_terms if term in haystack)
    if exact_terms:
        bonus += 0.18 * (matched / len(exact_terms))

    if any(hint in haystack for hint in _TROUBLESHOOTING_SOURCE_HINTS):
        bonus += 0.12

    if (
        "imagepullbackoff" in haystack
        or "errimagepull" in haystack
        or "oomkilled" in haystack
        or "crashloopbackoff" in haystack
    ):
        bonus += 0.15

    return bonus


# Learner Note: Reranker is part of the retrieval-augmented generation pipeline.
class Reranker:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent reranker within the retrieval-augmented generation pipeline.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.model = _get_cross_encoder(settings.reranker_model)

    # Learner note: Implements rerank, a key retrieval-quality step in the RAG pipeline.
    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Perform rerank for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        if not chunks:
            return []

        pairs = [(query, chunk.text) for chunk in chunks]
        rerank_scores = [float(score) for score in self.model.predict(pairs)]
        retrieval_scores = [float(chunk.retrieval_score or chunk.score or 0.0) for chunk in chunks]
        overlap_scores = [_keyword_overlap(query, chunk) for chunk in chunks]
        exact_token_bonuses = [_exact_token_bonus(query, chunk) for chunk in chunks]

        rerank_norm = _normalize(rerank_scores)
        retrieval_norm = _normalize(retrieval_scores)

        enriched: list[RetrievedChunk] = []
        for idx, chunk in enumerate(chunks):
            blended_score = (
                0.4 * rerank_norm[idx]
                + 0.3 * retrieval_norm[idx]
                + 0.3 * overlap_scores[idx]
                + exact_token_bonuses[idx]
            )
            enriched.append(
                RetrievedChunk(
                    text=chunk.text,
                    source=chunk.source,
                    score=float(blended_score),
                    retrieval_score=chunk.retrieval_score,
                    rerank_score=rerank_scores[idx],
                )
            )

        enriched.sort(key=lambda chunk: chunk.score, reverse=True)
        return enriched[:top_k]
