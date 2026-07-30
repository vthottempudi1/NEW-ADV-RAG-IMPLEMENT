from __future__ import annotations

import re

from app.config import settings
from app.models import RetrievedChunk
from app.rag.embedding_service import embed_texts
from app.rag.llm_service import generate
from app.rag.sparse_vector import fuse_rrf
from app.rag.vector_store import hybrid_search, search, sparse_search

_HYDE_SYSTEM_PROMPT = (
    "You generate hypothetical retrieval text for a Kubernetes operations "
    "knowledge base. Given a user's lay-language question, write a brief "
    "2-3 sentence hypothetical answer using Kubernetes terminology likely "
    "to appear in authoritative documentation. Map general infrastructure "
    "language to relevant concepts such as Deployments, Services, DNS, "
    "Horizontal Pod Autoscaling, PersistentVolumes, probes, scheduling, "
    "and resource policies when appropriate. "
    "The hypothetical answer is only a search aid, not factual evidence. "
    "Write only the hypothetical answer with no preamble."
)

def _normalize_text(text: str) -> str:
    """Collapse internal whitespace runs to single spaces and strip leading/trailing whitespace, for deduplication comparisons."""
    return re.sub(r"\s+", " ", text.strip())


class HyDERetriever:
    """Retriever implementing HyDE (Hypothetical Document Embeddings).

    Generates one or more LLM-written hypothetical answers to a question, retrieves
    documents for the original question plus each hypothesis, and fuses the result
    lists with Reciprocal Rank Fusion. The idea is that a plausible-sounding
    hypothetical answer is often lexically/semantically closer to the target
    documents than the raw question is.
    """

    def __init__(self, num_hypotheses: int | None = None) -> None:
        """Set how many hypothetical answers to generate per query, defaulting to `settings.hyde_num_hypotheses`."""
        self.num_hypotheses = num_hypotheses or settings.hyde_num_hypotheses

    def _generate_queries(self, question: str) -> list[str]:
        """Build the list of retrieval queries: the original question plus up to `num_hypotheses` LLM-generated hypothetical answers.

        Skips empty completions and de-duplicates against already-seen queries
        (via `_normalize_text`). Silently skips any hypothesis whose generation
        call raises. The original question is always first and always included.
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

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        mode: str = "dense",
    ) -> list[RetrievedChunk]:
        """Retrieve chunks for `question` using the HyDE technique, fused via RRF.

        Generates hypothetical-answer queries, then runs retrieval per query according
        to `mode`: "sparse" uses lexical search, "hybrid" combines dense embeddings with
        lexical search, and anything else (the default "dense") uses dense embedding
        search only. Per-query retrieval failures are swallowed so one bad query doesn't
        fail the whole call. Returns an empty list if the question is blank or every
        per-query retrieval attempt fails; otherwise returns the top `top_k` chunks
        after RRF fusion across all successful result lists.
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
