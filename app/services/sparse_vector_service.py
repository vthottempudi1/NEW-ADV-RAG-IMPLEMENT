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