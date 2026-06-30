from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.config import settings
from app.models import ChatResponse, RetrievedChunk
from Eval.schema import Golden


class SkippedIntent(Exception):
    """Raised when an eval intent is intentionally not supported."""

    pass

class Invoker(ABC):
    
    @abstractmethod
    def invoke(
        self, question: str, flags: dict, intent:str
    ) -> tuple[Any, list]:
        ...
      
    
class ServiceInvoker(Invoker):
    SUPPORTED_INTENTS = {"rag", "web_fallback"}

    def invoke(
            self, question: str, flags: dict, intent: str
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        if intent not in self.SUPPORTED_INTENTS:
            raise SkippedIntent(f"intent '{intent}' is not supported by the current service invoker")
        if intent == "web_fallback" and not settings.tavily_api_key:
            raise SkippedIntent("tavily_unset: TAVILY_API_KEY not configured")

        from app.services.rag_service import run_rag_with_trace_no_cache

        return run_rag_with_trace_no_cache(question, flags)


class FixtureInvoker(Invoker):
    """Deterministic invoker for CI-safe eval smoke runs."""

    def __init__(self, goldens: list[Golden]):
        self._goldens_by_question = {golden.question: golden for golden in goldens}

    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        golden = self._goldens_by_question.get(question)
        if golden is None:
            raise SkippedIntent(f"missing_fixture_for_question: {question}")

        sources = list(golden.golden_sources)
        chunks = [
            RetrievedChunk(
                text=self._chunk_text(golden, source),
                source=source,
                score=1.0,
                retrieval_score=1.0,
            )
            for source in sources
        ]

        route = {
            "sql": "sql",
            "hybrid": "hybrid",
            "web_fallback": "rag",
        }.get(intent, "rag")

        metadata = {
            "route": route,
            "retrieved_chunks": [
                {
                    "text": chunk.text,
                    "source": chunk.source,
                    "score": chunk.score,
                    "retrieval_score": chunk.retrieval_score,
                    "rerank_score": None,
                }
                for chunk in chunks
            ],
            "cache_hit": False,
            "reflection_iterations": 0,
            "reflection_score": None,
            "refined_question": None,
            "crag_score": 0.95 if intent == "web_fallback" else None,
            "crag_label": "relevant" if intent == "web_fallback" else None,
            "used_web_fallback": intent == "web_fallback",
        }

        response = ChatResponse(
            answer=self._answer_text(golden),
            sources=sources,
            confidence=0.95,
            cache_hit=False,
            metadata=metadata,
        )
        return response, chunks

    def _answer_text(self, golden: Golden) -> str:
        keywords = ", ".join(golden.golden_answer_keywords)
        if golden.intent == "sql":
            return f"Mock SQL answer for {golden.id}: {keywords}."
        if golden.intent == "hybrid":
            return f"Mock hybrid answer for {golden.id}: {keywords}."
        if golden.intent == "web_fallback":
            return f"Mock web fallback answer for {golden.id}: {keywords}."
        return f"Mock RAG answer for {golden.id}: {keywords}."

    def _chunk_text(self, golden: Golden, source: str) -> str:
        keywords = ", ".join(golden.golden_answer_keywords)
        return (
            f"Fixture context for {golden.id} from {source}. "
            f"Question: {golden.question} "
            f"Relevant terms: {keywords}."
        )
