from __future__ import annotations

import re
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.config import settings
from app.models import RetrievedChunk


@lru_cache(maxsize=2)
def _get_cross_encoder(model_name: str) -> CrossEncoder:
    """Load a ``CrossEncoder`` for ``model_name``, caching up to 2 instances per process.

    Avoids reloading the same transformer weights on every rerank call; the
    small cache size still allows a second model to be held if configuration
    changes at runtime.
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


def _normalize(values: list[float]) -> list[float]:
    """Min-max scale ``values`` to the ``[0, 1]`` range.

    Returns ``[]`` for empty input. If every value is equal (zero range),
    returns all ``1.0`` rather than dividing by zero.
    """
    if not values:
        return []

    low = min(values)
    high = max(values)

    if high == low:
        return [1.0 for _ in values]

    scale = high - low
    return [(value - low) / scale for value in values]


def _keyword_overlap(query: str, chunk: RetrievedChunk) -> float:
    """Return the fraction of the query's terms that appear in the chunk.

    Matches against the chunk's source name plus the first 400 characters of
    its text (lowercased). Returns ``0.0`` if the query yields no terms.
    """
    query_terms = _query_terms(query)
    if not query_terms:
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:400]}".lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return matched / len(query_terms)


def _query_terms(query: str) -> set[str]:
    """Extract a normalized, stopword-filtered set of search terms from a query.

    Tokenizes on word-ish characters, keeps lowercase tokens of length >= 2
    that aren't stopwords, and additionally splits each token on camelCase/
    digit boundaries (e.g. ``ImagePullBackOff`` -> ``image``, ``pull``,
    ``back``, ``off``) so mixed-case identifiers contribute their sub-words
    too. Known error identifiers are expanded via ``_TERM_EXPANSIONS`` (e.g.
    ``oomkilled`` also adds ``oom``, ``killed``, ``memory``, ``eviction``).
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


def _is_troubleshooting_query(query: str) -> bool:
    """Heuristically detect ops/error-style queries (e.g. "fix CrashLoopBackOff").

    Returns True if the query contains a known troubleshooting keyword (from
    ``_TROUBLESHOOTING_HINTS``), or if it contains a token of 6+ characters
    with an uppercase letter after its first position (catching mixed-case
    identifiers/error codes like ``ImagePullBackOff``).
    """
    lowered = query.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    for token in re.findall(r"[A-Za-z0-9_./:-]+", query):
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


def _exact_token_bonus(query: str, chunk: RetrievedChunk) -> float:
    """Compute a relevance bonus that favors troubleshooting-relevant chunks.

    Returns ``0.0`` unless ``_is_troubleshooting_query(query)`` is True.
    Otherwise adds up to three components based on the chunk's source name
    plus the first 800 characters of its text: up to 0.18 scaled by the
    fraction of query terms (length >= 4) found exactly, +0.12 if the chunk
    mentions troubleshooting-source hints (runbook, incident, etc.), and
    +0.15 if it contains a specific known Kubernetes error string
    (ImagePullBackOff, ErrImagePull, OOMKilled, CrashLoopBackOff).
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


class Reranker:
    """Reorder retrieved chunks by relevance using a cross-encoder plus keyword signals.

    Blends four signals into a single score per chunk: the cross-encoder's
    predicted relevance, the chunk's original retrieval score, lexical
    keyword overlap with the query, and (for troubleshooting-style queries)
    an exact-token bonus that favors runbook/incident content. This mitigates
    cases where the cross-encoder alone under-ranks chunks that contain exact
    error strings the user is searching for.
    """

    def __init__(self):
        """Load the configured cross-encoder model (``settings.reranker_model``)."""
        self.model = _get_cross_encoder(settings.reranker_model)

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Score and reorder ``chunks`` against ``query``, returning the top ``top_k``.

        For each chunk, computes: a cross-encoder score for the (query, text)
        pair, the chunk's prior retrieval score, a keyword-overlap score, and
        a troubleshooting exact-token bonus. The cross-encoder and retrieval
        scores are min-max normalized across the batch, then combined as
        ``0.4 * rerank + 0.3 * retrieval + 0.3 * overlap + exact_token_bonus``.
        Returns new ``RetrievedChunk`` objects (with ``rerank_score`` set)
        sorted descending by the blended score, truncated to ``top_k``.
        Returns ``[]`` if ``chunks`` is empty.
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
                    metadata=dict(chunk.metadata or {}),
                    score=float(blended_score),
                    retrieval_score=chunk.retrieval_score,
                    rerank_score=rerank_scores[idx],
                )
            )

        enriched.sort(key=lambda chunk: chunk.score, reverse=True)
        return enriched[:top_k]
