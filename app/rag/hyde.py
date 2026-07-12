from __future__ import annotations

import re

from app.config import settings
from app.models import RetrievedChunk
from app.rag.embedding_service import embed_texts
from app.rag.llm_service import generate
from app.rag.sparse_vector import fuse_rrf
from app.rag.vector_store import hybrid_search, search, sparse_search

_HYDE_SYSTEM_PROMPT = (
    "You are a helpful assistant. Given a user question, write a brief, plausible answer "
    "(2-3 sentences) that would help retrieve relevant documents. Write only the answer, "
    "with no preamble."
)


# Learner note: Encapsulates normalize text so this responsibility can be understood, tested, and changed independently.
def _normalize_text(text: str) -> str:
    """Support the retrieval-augmented generation pipeline by performing normalize text.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return re.sub(r"\s+", " ", text.strip())


# Learner Note: Hy d e retriever is part of the retrieval-augmented generation pipeline.
class HyDERetriever:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent hy d e retriever within the retrieval-augmented generation pipeline.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self, num_hypotheses: int | None = None) -> None:
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.num_hypotheses = num_hypotheses or settings.hyde_num_hypotheses

    # Learner note: Encapsulates generate queries so this responsibility can be understood, tested, and changed independently.
    def _generate_queries(self, question: str) -> list[str]:
        """Support the retrieval-augmented generation pipeline by performing generate queries.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        queries = [question.strip()]
        seen = {_normalize_text(queries[0])}

        for _ in range(self.num_hypotheses):
            try:
                result = generate(
                    system_prompt=_HYDE_SYSTEM_PROMPT,
                    user_message=question,
                    model=settings.llm_model_answer,
                    temperature=0.7,
                )
                hypothesis = (result.get("text") or "").strip()
                if not hypothesis:
                    continue
                normalized = _normalize_text(hypothesis)
                if normalized in seen:
                    continue
                seen.add(normalized)
                queries.append(hypothesis)
            except Exception:
                continue

        return queries

    # Learner note: Implements retrieve, a key retrieval-quality step in the RAG pipeline.
    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        mode: str = "dense",
    ) -> list[RetrievedChunk]:
        """Perform retrieve for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        if not question or not question.strip():
            return []

        queries = self._generate_queries(question)
        if not queries:
            return []

        result_lists: list[list[RetrievedChunk]] = []

        if mode == "sparse":
            for query_text in queries:
                try:
                    results = sparse_search(query_text, top_k=top_k)
                    if results:
                        result_lists.append(results)
                except Exception:
                    continue
        else:
            embeddings = embed_texts(queries)
            for query_text, embedding in zip(queries, embeddings, strict=True):
                try:
                    if mode == "hybrid":
                        results = hybrid_search(embedding, query_text, top_k=top_k)
                    else:
                        results = search(embedding, top_k=top_k)
                    if results:
                        result_lists.append(results)
                except Exception:
                    continue

        if not result_lists:
            return []

        fused = fuse_rrf(result_lists, rrf_k=settings.rrf_k)
        return fused[:top_k]
