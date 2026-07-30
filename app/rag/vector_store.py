from __future__ import annotations

import hashlib
import re
import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.models import RetrievedChunk
from app.rag.sparse_vector import SparseVectorIndex

VECTOR_SIZE = 1536
_TROUBLESHOOTING_HINTS = (
    "error",
    "fix",
    "troubleshoot",
    "troubleshooting",
    "debug",
    "debugging",
    "crash",
    "crashing",
    "restart",
    "restarting",
    "logs",
    "runbook",
    "incident",
    "oomkilled",
    "errimagepull",
    "imagepullbackoff",
    "crashloopbackoff",
)
_TROUBLESHOOTING_SOURCE_HINTS = (
    "troubleshooting",
    "runbook",
    "incident",
    "logging",
    "log",
    "debug",
    "eviction",
)
_TROUBLESHOOTING_EXPANSIONS = {
    "errimagepull": ("image", "pull", "registry", "imagepullbackoff"),
    "imagepullbackoff": ("image", "pull", "registry", "errimagepull"),
    "oomkilled": ("oom", "killed", "memory", "limit"),
    "crashloopbackoff": ("crash", "loop", "backoff", "restart", "logs"),
}

_sparse_index: SparseVectorIndex | None = None
_sparse_fitted = False
_sparse_lock = threading.Lock()


def _get_sparse_index() -> SparseVectorIndex:
    """Return the process-wide sparse index, building it lazily on first use.

    On a cache miss, scrolls every point out of the configured Qdrant
    collection (paginated, 500 at a time) to collect each point's `text`
    and `source` payload fields, then fits a new `SparseVectorIndex` over
    that document set. Uses double-checked locking around `_sparse_lock` so
    the expensive full-collection scroll and fit run at most once even
    under concurrent callers. The fitted index is cached until
    `reset_sparse_index` is called (e.g. after an upsert).
    """
    global _sparse_index, _sparse_fitted

    if _sparse_fitted and _sparse_index is not None:
        return _sparse_index

    with _sparse_lock:
        if _sparse_fitted and _sparse_index is not None:
            return _sparse_index

        client = get_client()
        documents: list[dict] = []
        offset = None

        while True:
            results, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                limit=500,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in results:
                documents.append(
                    {
                        "text": point.payload.get("text", ""),
                        "source": point.payload.get("source", ""),
                        "metadata": {
                            key: value
                            for key, value in point.payload.items()
                            if key not in {"text", "source"}
                        },
                    }
                )
            if offset is None:
                break

        _sparse_index = SparseVectorIndex()
        _sparse_index.fit(documents)
        _sparse_fitted = True

    return _sparse_index


def reset_sparse_index() -> None:
    """Invalidate the cached sparse index so it is rebuilt from Qdrant on next use.

    Called after any collection mutation (upsert, recreate) so sparse and
    hybrid search always see up-to-date content.
    """
    global _sparse_fitted
    with _sparse_lock:
        _sparse_fitted = False


def get_client() -> QdrantClient:
    """Construct a new QdrantClient from configured settings.

    Uses `settings.qdrant_url` with a 30-second request timeout, and
    includes `settings.qdrant_api_key` when one is configured.
    """
    kwargs = {
        "url": settings.qdrant_url,
        "timeout": 30,
    }
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


def ensure_collection() -> None:
    """Create the configured Qdrant collection if it does not already exist.

    Uses a fixed dense vector space of size `VECTOR_SIZE` with cosine
    distance. Idempotent: does nothing if the collection is already
    present.
    """
    client = get_client()
    existing = {collection.name for collection in client.get_collections().collections}

    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def recreate_collection() -> None:
    """Drop and recreate the configured Qdrant collection, discarding all existing points.

    Deletes the collection if present, recreates it via `ensure_collection`,
    and resets the cached sparse index so it rebuilds empty on next use.
    Intended for full reindex/reset workflows, not routine ingestion.
    """
    client = get_client()
    existing = {collection.name for collection in client.get_collections().collections}

    if settings.qdrant_collection in existing:
        client.delete_collection(collection_name=settings.qdrant_collection)

    ensure_collection()
    reset_sparse_index()


def _chunk_id(source: str, text: str) -> str:
    """Derive a deterministic Qdrant point ID (UUID) from a chunk's source and text.

    Hashing `source` and `text` together with SHA-256 means re-ingesting
    identical content always maps to the same point ID, so upserts
    overwrite the existing point instead of creating a duplicate.
    """
    digest = hashlib.sha256(f"{source}\n{text}".encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


def _is_troubleshooting_query(query: str) -> bool:
    """Return True if `query` reads as an operational troubleshooting question.

    True if the query contains a known troubleshooting keyword (error,
    debug, crashloopbackoff, ...), or contains a token of 6+ characters
    with an internal uppercase letter (e.g. an error code like
    `ImagePullBackOff`).
    """
    lowered = query.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    tokens = re.findall(r"[A-Za-z0-9_./:-]+", query)
    for token in tokens:
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


def _keyword_overlap(query: str, chunk: RetrievedChunk) -> float:
    """Return the fraction of `query`'s significant terms found in `chunk`.

    Considers query terms of 3+ characters, and checks for their literal
    presence in the chunk's source plus the first 600 characters of its
    text (case-insensitive). Returns 0.0 if the query has no qualifying
    terms.
    """
    query_terms = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./:-]+", query)
        if len(token) >= 3
    }
    if not query_terms:
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:600]}".lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return matched / len(query_terms)


def _expanded_sparse_query(query: str) -> str:
    """Expand a troubleshooting `query` with related terms to improve sparse recall.

    Returns `query` unchanged if it is not a troubleshooting query.
    Otherwise splits CamelCase-style tokens into lowercase parts (e.g.
    `ImagePullBackOff` -> "image pull back off") and appends known synonym
    expansions from `_TROUBLESHOOTING_EXPANSIONS` (e.g. "oomkilled" ->
    "oom killed memory limit"), so BM25-style sparse search can match
    documents phrased with different terminology. Duplicate pieces are
    removed while preserving order.
    """
    if not _is_troubleshooting_query(query):
        return query

    pieces: list[str] = [query]
    for token in re.findall(r"[A-Za-z0-9_./:-]+", query):
        lowered = token.lower()
        camel_parts = [part.lower() for part in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", token)]
        if camel_parts:
            pieces.extend(camel_parts)
        if lowered in _TROUBLESHOOTING_EXPANSIONS:
            pieces.extend(_TROUBLESHOOTING_EXPANSIONS[lowered])

    return " ".join(dict.fromkeys(piece for piece in pieces if piece))


def _troubleshooting_terms(query: str) -> set[str]:
    """Return the set of lowercase terms (4+ characters) from the troubleshooting-expanded form of `query`.

    Used as the term set for troubleshooting-specific relevance scoring.
    """
    expanded = _expanded_sparse_query(query)
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./:-]+", expanded)
        if len(token) >= 4
    }


def _source_bias(chunk: RetrievedChunk, troubleshooting_query: bool) -> float:
    """Return an additive score boost for troubleshooting-relevant chunks.

    Returns 0.0 unless `troubleshooting_query` is True. Otherwise adds 0.06
    if the chunk's source/text mentions a general troubleshooting source
    hint (runbook, incident, logs, ...), plus an additional 0.08 if it
    contains an exact match for a canonical Kubernetes failure signature
    (OOMKilled, ErrImagePull, CrashLoopBackOff).
    """
    if not troubleshooting_query:
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:200]}".lower()
    bias = 0.0
    if any(hint in haystack for hint in _TROUBLESHOOTING_SOURCE_HINTS):
        bias += 0.06
    if "oomkilled" in haystack or "errimagepull" in haystack or "crashloopbackoff" in haystack:
        bias += 0.08
    return bias


def _troubleshooting_match_score(query: str, chunk: RetrievedChunk) -> float:
    """Score how strongly `chunk` matches a troubleshooting `query`.

    Returns 0.0 if `query` is not a troubleshooting query or has no
    expanded terms. Otherwise combines a proportional term-overlap score
    (up to 0.8) with flat bonuses (+0.45 each) for exact matches on
    canonical failure signatures (`imagepullbackoff`/`oom_killer`,
    `oomkilled`/`errimagepull`/`crashloopbackoff`) and +0.2 for a
    troubleshooting source hint. Used to boost/re-rank chunks during hybrid
    retrieval.
    """
    if not _is_troubleshooting_query(query):
        return 0.0

    terms = _troubleshooting_terms(query)
    if not terms:
        return 0.0

    haystack = f"{chunk.source} {chunk.text[:1200]}".lower()
    matched = sum(1 for term in terms if term in haystack)
    score = 0.8 * (matched / len(terms))

    if "imagepullbackoff" in haystack or "oom_killer" in haystack:
        score += 0.45
    if "oomkilled" in haystack or "errimagepull" in haystack or "crashloopbackoff" in haystack:
        score += 0.45
    if any(hint in haystack for hint in _TROUBLESHOOTING_SOURCE_HINTS):
        score += 0.2
    return score


def _is_strong_troubleshooting_chunk(query: str, chunk: RetrievedChunk) -> bool:
    """Return True if `chunk` is a high-confidence match for a troubleshooting `query`.

    True if the troubleshooting match score alone is high (>= 0.45), or a
    moderate match score (>= 0.25) is corroborated by keyword overlap
    (>= 0.15), or a source bias hit (>= 0.06) is corroborated by keyword
    overlap (>= 0.12). Used to promote strongly relevant troubleshooting
    chunks to the front of hybrid search results.
    """
    match_score = _troubleshooting_match_score(query, chunk)
    overlap = _keyword_overlap(query, chunk)
    source_bias = _source_bias(chunk, True)
    return (
        match_score >= 0.45
        or (match_score >= 0.25 and overlap >= 0.15)
        or (source_bias >= 0.06 and overlap >= 0.12)
    )


def upsert_chunks(chunks: list[RetrievedChunk], embeddings: list[list[float]]) -> None:
    """Embed-upsert `chunks` into the configured Qdrant collection.

    Ensures the collection exists, then builds one `PointStruct` per chunk
    by pairing each chunk with its corresponding vector from `embeddings`
    via `zip(..., strict=True)` — the two lists must be the same length and
    in matching order, or this raises. Each point's ID is derived
    deterministically from the chunk's source and text (`_chunk_id`), so
    re-ingesting identical content overwrites the existing point rather
    than duplicating it. The chunk's `metadata` dict, `text`, and `source`
    are all stored in the point payload.

    After upserting, invalidates the cached sparse index (`reset_sparse_index`)
    so subsequent sparse/hybrid searches immediately reflect the new chunks.
    """
    ensure_collection()
    client = get_client()

    points = [
        PointStruct(
            id=_chunk_id(chunk.source, chunk.text),
            vector=embedding,
            payload={
                **chunk.metadata,
                "text": chunk.text,
                "source": chunk.source,
            },
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]

    client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )
    reset_sparse_index()


def search(query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
    """Run a dense vector similarity search in Qdrant and return the top `top_k` chunks.

    Queries the configured collection with `query_embedding` and converts
    each result into a `RetrievedChunk`, with `score` and `retrieval_score`
    set to Qdrant's similarity score and all payload fields other than
    `text`/`source` folded into `metadata`.
    """
    client = get_client()

    results = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_embedding,
        limit=top_k,
        with_payload=True,
    ).points

    return [
        RetrievedChunk(
            text=point.payload.get("text", ""),
            source=point.payload.get("source", ""),
            metadata={
                key: value
                for key, value in point.payload.items()
                if key not in {"text", "source"}
            },
            score=float(point.score),
            retrieval_score=float(point.score),
        )
        for point in results
    ]


def sparse_search(query: str, top_k: int = 5) -> list[RetrievedChunk]:
    """Run a sparse (lexical) search over the cached sparse index and return up to `top_k` chunks.

    Expands `query` for troubleshooting terminology (`_expanded_sparse_query`)
    before searching the index. For non-troubleshooting queries, returns
    the sparse index's own top-`top_k` results unchanged.

    For troubleshooting queries, additionally scans every document in the
    sparse index for troubleshooting-term overlap — including documents
    the base sparse ranking may have missed — scoring each by term overlap
    plus bonuses for troubleshooting source hints and canonical failure
    signatures (ImagePullBackOff, OOMKilled, CrashLoopBackOff). These
    "rescue" candidates are merged with the original results (deduplicated
    by a `source:text-prefix` key, keeping the higher score on collision)
    and the combined set is re-sorted by score and truncated to `top_k`.
    This recovers troubleshooting-relevant chunks that plain sparse ranking
    might otherwise rank too low to surface.
    """
    index = _get_sparse_index()
    expanded_query = _expanded_sparse_query(query)
    results = index.search(expanded_query, top_k=top_k)

    if not _is_troubleshooting_query(query):
        return results

    terms = _troubleshooting_terms(query)
    rescues: list[RetrievedChunk] = []

    for doc in index.documents:
        haystack = f"{doc['source']} {doc['text'][:1200]}".lower()
        matched = sum(1 for term in terms if term in haystack)
        if not matched:
            continue

        score = matched / max(len(terms), 1)
        if any(hint in haystack for hint in _TROUBLESHOOTING_SOURCE_HINTS):
            score += 0.25
        if "imagepullbackoff" in haystack or "oomkilled" in haystack or "crashloopbackoff" in haystack:
            score += 0.35

        rescues.append(
            RetrievedChunk(
                text=doc["text"],
                source=doc["source"],
                metadata=dict(doc.get("metadata") or {}),
                score=score,
                retrieval_score=score,
            )
        )

    merged: dict[str, RetrievedChunk] = {
        f"{chunk.source}:{chunk.text[:60]}": chunk for chunk in results
    }
    for chunk in sorted(rescues, key=lambda item: item.score, reverse=True)[: top_k * 4]:
        key = f"{chunk.source}:{chunk.text[:60]}"
        existing = merged.get(key)
        if existing is None or chunk.score > existing.score:
            merged[key] = chunk

    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]


def hybrid_search(
    query_embedding: list[float],
    query: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Combine dense and sparse retrieval into one ranked result set via weighted reciprocal rank fusion.

    Runs both `search` (dense) and `sparse_search` (sparse) against
    expanded candidate pools (2x `top_k` for dense; 2x or 4x for sparse
    depending on whether `query` is a troubleshooting question), then fuses
    the two rankings with RRF (`k=60`). Dense and sparse contributions are
    weighted differently for troubleshooting queries (dense down-weighted
    to 0.8, sparse up-weighted to 2.8) versus non-troubleshooting queries
    (both weighted 1.0), and each chunk's fused score additionally accrues
    troubleshooting-aware bonuses: keyword overlap, exact troubleshooting
    match score, and source bias.

    Candidates from both lists are deduplicated by a `source:text-prefix`
    key, with scores summed across appearances in both lists. If `query` is
    a troubleshooting query, chunks classified as "strong" by
    `_is_strong_troubleshooting_chunk` are moved to the front of the
    ranking ahead of the remaining fused-score order, before the result is
    truncated to `top_k`.

    Returns `RetrievedChunk` models whose `score`/`retrieval_score` reflect
    the final fused score rather than either underlying dense or sparse
    score.
    """
    k = 60
    troubleshooting_query = _is_troubleshooting_query(query)
    dense_multiplier = 2
    sparse_multiplier = 4 if troubleshooting_query else 2
    dense_weight = 0.8 if troubleshooting_query else 1.0
    sparse_weight = 2.8 if troubleshooting_query else 1.0

    dense = search(query_embedding, top_k=top_k * dense_multiplier)
    sparse = sparse_search(query, top_k=top_k * sparse_multiplier)

    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}

    for rank, chunk in enumerate(dense):
        key = f"{chunk.source}:{chunk.text[:60]}"
        lexical_bonus = 0.04 * _keyword_overlap(query, chunk) if troubleshooting_query else 0.0
        match_bonus = _troubleshooting_match_score(query, chunk)
        scores[key] = (
            scores.get(key, 0.0)
            + dense_weight / (k + rank + 1)
            + lexical_bonus
            + match_bonus
            + _source_bias(chunk, troubleshooting_query)
        )
        chunks[key] = chunk

    for rank, chunk in enumerate(sparse):
        key = f"{chunk.source}:{chunk.text[:60]}"
        lexical_bonus = 0.08 * _keyword_overlap(query, chunk) if troubleshooting_query else 0.0
        match_bonus = _troubleshooting_match_score(query, chunk)
        scores[key] = (
            scores.get(key, 0.0)
            + sparse_weight / (k + rank + 1)
            + lexical_bonus
            + match_bonus
            + _source_bias(chunk, troubleshooting_query)
        )
        chunks[key] = chunk

    ranked_keys = sorted(scores, key=lambda key: scores[key], reverse=True)

    if troubleshooting_query:
        strong_keys = [
            key for key in ranked_keys if _is_strong_troubleshooting_chunk(query, chunks[key])
        ]
        if strong_keys:
            ranked_keys = strong_keys + [key for key in ranked_keys if key not in strong_keys]

    ranked_keys = ranked_keys[:top_k]

    return [
        RetrievedChunk(
            text=chunks[key].text,
            source=chunks[key].source,
            metadata=dict(chunks[key].metadata or {}),
            score=float(scores[key]),
            retrieval_score=float(scores[key]),
        )
        for key in ranked_keys
    ]
