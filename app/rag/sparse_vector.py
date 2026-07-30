from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from app.models import RetrievedChunk


class SparseVectorIndex:
    """In-memory TF-IDF sparse retrieval index over a list of documents.

    Wraps scikit-learn's TfidfVectorizer to support keyword-style lexical search
    (as opposed to dense embedding search), useful standalone or fused with dense
    results for hybrid retrieval.
    """

    def __init__(self):
        """Create an unfitted index with English stop-word filtering and no documents loaded yet."""
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.documents: list[dict] = []
        self.matrix = None

    def fit(self, documents: list[dict]) -> None:
        """Build the TF-IDF matrix from `documents` (each a dict with a "text" key).

        Replaces any previously fitted state. If `documents` is empty, clears the
        matrix to None instead of fitting the vectorizer.
        """
        self.documents = documents
        texts = [doc["text"] for doc in documents]

        if not texts:
            self.matrix = None
            return

        self.matrix = self.vectorizer.fit_transform(texts)

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Return up to `top_k` documents ranked by TF-IDF cosine-style similarity to `query`.

        Documents with a non-positive score are dropped. Returns an empty list if
        the index hasn't been fit or has no documents.
        """
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
                    metadata=dict(doc.get("metadata") or {}),
                    score=score,
                    retrieval_score=score,
                )
            )

        return results


def fuse_rrf(
    result_lists: list[list[RetrievedChunk]],
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Merge multiple ranked result lists into one using Reciprocal Rank Fusion.

    Each chunk's score is the sum of `1 / (rrf_k + rank + 1)` across every list it
    appears in (deduplicated by chunk text), so items ranked highly by multiple
    sources float to the top. `rrf_k` dampens the influence of rank position (higher
    values flatten the score curve). Returns chunks sorted by fused score descending.
    """
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
                    "metadata": dict(chunk.metadata or {}),
                }

    return [
        RetrievedChunk(
            text=text,
            source=meta[text]["source"],
            metadata=dict(meta[text].get("metadata") or {}),
            score=float(score),
            retrieval_score=float(score),
        )
        for text, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
