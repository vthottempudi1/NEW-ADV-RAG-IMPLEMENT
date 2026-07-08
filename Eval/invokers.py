from __future__ import annotations

from abc import ABC, abstractmethod
import json
import uuid
from typing import Any

import httpx

from app.config import settings
from app.models import ChatResponse, ResponseMetadata, RetrievedChunk, RetrievedChunkPreview
from Eval.schema import Golden


class SkippedIntent(Exception):
    """Raised when an eval intent is intentionally not supported."""

    pass


class Invoker(ABC):
    @abstractmethod
    def invoke(
        self, question: str, flags: dict, intent: str
    ) -> tuple[Any, list]:
        ...


class ServiceInvoker(Invoker):
    SUPPORTED_INTENTS = {"rag", "web_fallback", "sql", "hybrid"}

    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        if intent not in self.SUPPORTED_INTENTS:
            raise SkippedIntent(
                f"intent '{intent}' is not supported by the current local service invoker"
            )
        if intent == "web_fallback" and not settings.tavily_api_key:
            raise SkippedIntent("tavily_unset: TAVILY_API_KEY not configured")

        if intent == "sql":
            return self._invoke_sql(question)
        if intent == "hybrid":
            return self._invoke_hybrid(question, flags)

        from app.services.rag_service import run_rag_with_trace_no_cache
        return run_rag_with_trace_no_cache(question, flags)

    def _invoke_sql(self, question: str) -> tuple[ChatResponse, list[RetrievedChunk]]:
        from app.core.graph import build_sql_execution_result
        from app.services.sql_service import SQLService

        service = SQLService()
        generated = service.generate_sql(question)
        sql = generated["sql"]
        rows = service.execute_sql(sql)
        result = build_sql_execution_result(question, sql, rows)
        response = ChatResponse(
            answer=result["final_answer"],
            sources=result["sources"],
            confidence=result["confidence"],
            cache_hit=result["cache_hit"],
            metadata=result["metadata"],
        )
        row_chunks = [
            RetrievedChunk(
                text=chunk.text,
                source=chunk.source,
                score=chunk.score,
                retrieval_score=chunk.retrieval_score,
                rerank_score=chunk.rerank_score,
            )
            for chunk in response.metadata.retrieved_chunks
        ]
        return response, row_chunks

    def _invoke_hybrid(
        self,
        question: str,
        flags: dict,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        from app.core.graph import build_hybrid_execution_result
        from app.services.rag_service import run_rag_with_trace_no_cache
        from app.services.sql_service import SQLService

        rag_response, rag_chunks = run_rag_with_trace_no_cache(question, flags)

        service = SQLService()
        generated = service.generate_sql(question)
        sql = generated["sql"]
        rows = service.execute_sql(sql)

        sql_chunks = [
            RetrievedChunk(
                text=json.dumps(row, default=str),
                source="database query",
                score=1.0,
                retrieval_score=1.0,
            )
            for row in rows
        ]
        result = build_hybrid_execution_result(
            question=question,
            sql=sql,
            rows=rows,
            rag_sources=rag_response.sources,
            rag_confidence=rag_response.confidence,
            rag_metadata=rag_response.metadata.model_dump(),
        )
        response = ChatResponse(
            answer=result["final_answer"],
            sources=result["sources"],
            confidence=result["confidence"],
            cache_hit=result["cache_hit"],
            metadata=result["metadata"],
        )
        combined_chunks = rag_chunks + sql_chunks
        return response, combined_chunks


class HttpServiceInvoker(Invoker):
    def __init__(
        self,
        api_base: str,
        username: str | None = None,
        password: str = "Test123!",
        token: str | None = None,
        approve_sql: bool = True,
        timeout: float = 120.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.username = username or (
            "eval." + uuid.uuid4().hex[:12] + "@example.com"
        )
        self.password = password
        self.approve_sql = approve_sql
        self._client = httpx.Client(timeout=timeout)
        self._token = token or self._bootstrap_token()

    def close(self) -> None:
        self._client.close()

    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        payload = {
            "question": question,
            "top_k": int(flags.get("top_k", 5)),
            "search_mode": flags.get("search_mode", "dense"),
            "enable_rerank": bool(flags.get("enable_rerank", False)),
            "enable_hyde": bool(flags.get("enable_hyde", False)),
            "enable_crag": bool(flags.get("enable_crag", False)),
            "enable_self_reflective": bool(
                flags.get("enable_self_reflective", False)
            ),
        }

        response = self._client.post(
            f"{self.api_base}/query",
            json=payload,
            headers=self._auth_headers(),
        )
        data = self._decode_json(response)

        if response.status_code != 200:
            raise RuntimeError(
                f"http_eval_query_failed: status={response.status_code} detail={self._detail_text(data)}"
            )

        if isinstance(data, dict) and data.get("pending_sql"):
            if not self.approve_sql:
                raise SkippedIntent(
                    f"http_sql_approval_required: query '{question}' needs approval"
                )

            approve_response = self._client.post(
                f"{self.api_base}/query/sql/execute",
                json={
                    "query_id": data["pending_sql"]["query_id"],
                    "approved": True,
                },
                headers=self._auth_headers(),
            )
            approved_data = self._decode_json(approve_response)
            if approve_response.status_code != 200:
                raise RuntimeError(
                    "http_eval_sql_approval_failed: "
                    f"status={approve_response.status_code} detail={self._detail_text(approved_data)}"
                )
            data = approved_data

        response_model = ChatResponse.model_validate(data)
        chunks = [
            RetrievedChunk.model_validate(
                chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
            )
            for chunk in response_model.metadata.retrieved_chunks
        ]
        return response_model, chunks

    def _bootstrap_token(self) -> str:
        register_payload = {
            "username": self.username,
            "password": self.password,
        }
        response = self._client.post(
            f"{self.api_base}/auth/register",
            json=register_payload,
        )
        data = self._decode_json(response)
        if response.status_code not in {200, 201}:
            raise RuntimeError(
                "http_eval_auth_failed: "
                f"status={response.status_code} detail={self._detail_text(data)}"
            )
        if not isinstance(data, dict) or not data.get("token"):
            raise RuntimeError("http_eval_auth_failed: token missing from auth response")
        return str(data["token"])

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            return response.text

    @staticmethod
    def _detail_text(payload: Any) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
        return str(payload)


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
