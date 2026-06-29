from __future__ import annotations

from sentence_transformers import CrossEncoder

from app.config import settings
from app.models import RetrievedChunk


class Reranker:
    def __init__(self):
        self.model = CrossEncoder(settings.reranker_model)

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self.model.predict(pairs)

        enriched: list[RetrievedChunk] = []
        for chunk, score in zip(chunks, scores, strict=True):
            enriched.append(
                RetrievedChunk(
                    text=chunk.text,
                    source=chunk.source,
                    score=float(score),
                    retrieval_score=chunk.retrieval_score,
                    rerank_score=float(score),
                )
            )

        enriched.sort(key=lambda chunk: chunk.rerank_score or 0.0, reverse=True)
        return enriched[:top_k]