from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from app.models import RetrievedChunk


class SparseVectorIndex:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.documents: list[dict] = []
        self.matrix = None

    def fit(self, documents: list[dict]) -> None:
        self.documents = documents
        texts = [doc["text"] for doc in documents]

        if not texts:
            self.matrix = None
            return

        self.matrix = self.vectorizer.fit_transform(texts)

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if self.matrix is None or not self.documents:
            return []

        query_vec = self.vectorizer.transform([query])
        scores = (self.matrix @ query_vec.T).toarray().ravel()

        ranked_indices = scores.argsort()[::-1][:top_k]
        results: list[RetrievedChunk] = []

        for idx in ranked_indices:
            score = float(scores[idx])
            if score <= 0:
                continue

            doc = self.documents[idx]
            results.append(
                RetrievedChunk(
                    text=doc["text"],
                    source=doc["source"],
                    score=score,
                    retrieval_score=score,
                )
            )

        return results


def fuse_rrf(
    result_lists: list[list[RetrievedChunk]],
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    meta: dict[str, dict[str, str]] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            key = chunk.text
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in meta:
                meta[key] = {
                    "text": chunk.text,
                    "source": chunk.source,
                }

    return [
        RetrievedChunk(
            text=text,
            source=meta[text]["source"],
            score=float(score),
            retrieval_score=float(score),
        )
        for text, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
