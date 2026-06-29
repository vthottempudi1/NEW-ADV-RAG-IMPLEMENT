from __future__ import annotations

from app.config import settings
from app.services.embedding_service import embed_texts
from app.services.llm_service import generate
from app.services.vector_store import hybrid_search, search, sparse_search


class HyDERetriever:
    def _generate_hypotheses(self, question: str) -> list[str]:
        system = (
            "You generate short hypothetical answers for retrieval. "
            "Do not explain your reasoning. Return only useful answer text."
        )

        hypotheses: list[str] = []
        for _ in range(settings.hyde_num_hypotheses):
            result = generate(
                system_prompt=system,
                user_message=f"Question: {question}",
                temperature=0.3,
            )
            text = (result.get("text") or "").strip()
            if text:
                hypotheses.append(text)

        if not hypotheses:
            hypotheses.append(question)

        return hypotheses

    def retrieve(self, question: str, top_k: int = 5, mode: str = "dense"):
        hypotheses = self._generate_hypotheses(question)

        if mode == "sparse":
            merged_query = " ".join(hypotheses)
            return sparse_search(merged_query, top_k=top_k)

        merged_text = "\n".join(hypotheses)
        query_embedding = embed_texts([merged_text])[0]

        if mode == "hybrid":
            return hybrid_search(query_embedding, merged_text, top_k=top_k)

        return search(query_embedding, top_k=top_k)