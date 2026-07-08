from __future__ import annotations

import hashlib
import re
import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.models import RetrievedChunk
from app.services.sparse_vector_service import SparseVectorIndex


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
                    }
                )
            if offset is None:
                break

        _sparse_index = SparseVectorIndex()
        _sparse_index.fit(documents)
        _sparse_fitted = True

    return _sparse_index


def reset_sparse_index() -> None:
    global _sparse_fitted
    with _sparse_lock:
        _sparse_fitted = False


def get_client() -> QdrantClient:
    kwargs = {
        "url": settings.qdrant_url,
        "timeout": 30,
    }
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


def ensure_collection() -> None:
    client = get_client()
    existing = {collection.name for collection in client.get_collections().collections}

    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def recreate_collection() -> None:
    client = get_client()
    existing = {collection.name for collection in client.get_collections().collections}

    if settings.qdrant_collection in existing:
        client.delete_collection(collection_name=settings.qdrant_collection)

    ensure_collection()
    reset_sparse_index()


def _chunk_id(source: str, text: str) -> str:
    digest = hashlib.sha256(f"{source}\n{text}".encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


def _is_troubleshooting_query(query: str) -> bool:
    lowered = query.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    tokens = re.findall(r"[A-Za-z0-9_./:-]+", query)
    for token in tokens:
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


def _keyword_overlap(query: str, chunk: RetrievedChunk) -> float:
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
    expanded = _expanded_sparse_query(query)
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./:-]+", expanded)
        if len(token) >= 4
    }


def _source_bias(chunk: RetrievedChunk, troubleshooting_query: bool) -> float:
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
    match_score = _troubleshooting_match_score(query, chunk)
    overlap = _keyword_overlap(query, chunk)
    source_bias = _source_bias(chunk, True)
    return (
        match_score >= 0.45
        or (match_score >= 0.25 and overlap >= 0.15)
        or (source_bias >= 0.06 and overlap >= 0.12)
    )


def upsert_chunks(chunks: list[RetrievedChunk], embeddings: list[list[float]]) -> None:
    ensure_collection()
    client = get_client()

    points = [
        PointStruct(
            id=_chunk_id(chunk.source, chunk.text),
            vector=embedding,
            payload={
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
            score=float(point.score),
            retrieval_score=float(point.score),
        )
        for point in results
    ]


def sparse_search(query: str, top_k: int = 5) -> list[RetrievedChunk]:
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
            score=float(scores[key]),
            retrieval_score=float(scores[key]),
        )
        for key in ranked_keys
    ]
