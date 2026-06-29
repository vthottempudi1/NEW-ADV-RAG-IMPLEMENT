from __future__ import annotations

import hashlib
import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.models import RetrievedChunk
from app.services.sparse_vector_service import SparseVectorIndex


VECTOR_SIZE = 1536

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
    return QdrantClient(url=settings.qdrant_url, timeout=30)


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
    return _get_sparse_index().search(query, top_k=top_k)


def hybrid_search(
    query_embedding: list[float],
    query: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    k = 60
    dense = search(query_embedding, top_k=top_k * 2)
    sparse = sparse_search(query, top_k=top_k * 2)

    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}

    for rank, chunk in enumerate(dense):
        key = f"{chunk.source}:{chunk.text[:60]}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        chunks[key] = chunk

    for rank, chunk in enumerate(sparse):
        key = f"{chunk.source}:{chunk.text[:60]}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        chunks[key] = chunk

    ranked_keys = sorted(scores, key=lambda key: scores[key], reverse=True)[:top_k]

    return [
        RetrievedChunk(
            text=chunks[key].text,
            source=chunks[key].source,
            score=float(scores[key]),
            retrieval_score=float(scores[key]),
        )
        for key in ranked_keys
    ]