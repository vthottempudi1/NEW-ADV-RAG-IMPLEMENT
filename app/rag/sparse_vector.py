from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from app.models import RetrievedChunk


# Learner Note: Sparse vector index is part of the retrieval-augmented generation pipeline.
class SparseVectorIndex:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent sparse vector index within the retrieval-augmented generation pipeline.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.documents: list[dict] = []
        self.matrix = None

    # Learner note: Encapsulates fit so this responsibility can be understood, tested, and changed independently.
    def fit(self, documents: list[dict]) -> None:
        """Perform fit for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        self.documents = documents
        texts = [doc["text"] for doc in documents]

        if not texts:
            self.matrix = None
            return

        self.matrix = self.vectorizer.fit_transform(texts)

    # Learner note: Implements search, a key retrieval-quality step in the RAG pipeline.
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Perform search for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
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
                    score=score,
                    retrieval_score=score,
                )
            )

        return results


# Learner note: Implements fuse rrf, a key retrieval-quality step in the RAG pipeline.
def fuse_rrf(
    result_lists: list[list[RetrievedChunk]],
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Perform fuse rrf for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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
