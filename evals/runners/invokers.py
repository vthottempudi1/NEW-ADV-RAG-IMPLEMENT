from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import settings
from app.models import ChatResponse, RetrievedChunk
from app.rag.hybrid_question import derive_hybrid_rag_question
from evals.datasets.schema import Golden


# Note: Skipped intent is part of the evaluation and quality-gate framework.
class SkippedIntent(Exception):
    """Raised when an eval intent is intentionally not supported."""

    pass


# Note: Invoker is part of the evaluation and quality-gate framework.
class Invoker(ABC):
    """Represent invoker within the evaluation and quality-gate framework.

    Note:
        This class groups state and behavior behind a clear, testable contract.
    """

    # Note: Orchestrates invoke, making this function a clear execution boundary for learners and tests.
    @abstractmethod
    def invoke(
        self, question: str, flags: dict, intent: str
    ) -> tuple[Any, list]:
        """Perform invoke for the evaluation and quality-gate framework.

        Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        ...


# Note: Service invoker is part of the evaluation and quality-gate framework.
class ServiceInvoker(Invoker):
    """Represent service invoker within the evaluation and quality-gate framework.

    Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    SUPPORTED_INTENTS = {"rag", "web_fallback", "sql", "hybrid", "clarification"}

    # Note: Orchestrates invoke, making this function a clear execution boundary for learners and tests.
    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        """Perform invoke for the evaluation and quality-gate framework.

        Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
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
        if intent == "clarification":
            from app.rag.clarification import detect_clarification_need

            decision = detect_clarification_need(question)
            if decision is None:
                raise RuntimeError("expected clarification decision was not produced")
            return (
                ChatResponse(
                    answer=decision.prompt,
                    sources=[],
                    confidence=1.0,
                    metadata={
                        "route": "clarification",
                        "needs_clarification": True,
                        "clarification_question": decision.prompt,
                        "clarification_reason": decision.reason,
                        "clarification_type": decision.ambiguity_type,
                    },
                ),
                [],
            )

        from app.rag.service import run_rag_with_trace_no_cache
        return run_rag_with_trace_no_cache(question, flags)

    # Note: Encapsulates invoke sql so this responsibility can be understood, tested, and changed independently.
    def _invoke_sql(self, question: str) -> tuple[ChatResponse, list[RetrievedChunk]]:
        """Support the evaluation and quality-gate framework by performing invoke sql.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        from app.core.graph import build_sql_execution_result
        from app.sql.service import SQLService

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

    # Note: Encapsulates invoke hybrid so this responsibility can be understood, tested, and changed independently.
    def _invoke_hybrid(
        self,
        question: str,
        flags: dict,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        """Support the evaluation and quality-gate framework by performing invoke hybrid.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        from app.core.graph import build_hybrid_execution_result
        from app.rag.service import run_rag_with_trace_no_cache
        from app.sql.service import SQLService

        # Hybrid questions contain two independent evidence needs.  Sending the
        # SQL clause into document retrieval lowers relevance, so retrieve only
        # with the document-focused clause used by the production graph.
        rag_question = derive_hybrid_rag_question(question)
        rag_response, rag_chunks = run_rag_with_trace_no_cache(rag_question, flags)

        service = SQLService()
        generated = service.generate_sql(question)
        sql = generated["sql"]
        rows = service.execute_sql(sql)

        # One consolidated SQL chunk gives the evaluator the complete database
        # evidence without penalizing queries that legitimately return many rows.
        sql_chunks = [
            RetrievedChunk(
                text=(
                    "Database evidence for the quantitative part of this question: "
                    f"{question}\nSQL Results:\n"
                    + json.dumps(rows, indent=2, default=str)
                ),
                source="database query",
                score=1.0,
                retrieval_score=1.0,
            )
        ] if rows else []
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


# Note: Http service invoker is part of the evaluation and quality-gate framework.
class HttpServiceInvoker(Invoker):
    # Note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent http service invoker within the evaluation and quality-gate framework.

    Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    # Note: Init is part of the evaluation and quality-gate framework.
    def __init__(
        self,
        api_base: str,
        username: str | None = None,
        password: str = "Test123!",
        token: str | None = None,
        approve_sql: bool = True,
        timeout: float = 120.0,
    ):
        """Initialize init dependencies and runtime state.

        Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.api_base = api_base.rstrip("/")
        self.username = username or (
            "eval." + uuid.uuid4().hex[:12] + "@example.com"
        )
        self.password = password
        self.approve_sql = approve_sql
        self._client = httpx.Client(timeout=timeout)
        self._token = token or self._bootstrap_token()

    # Note: Encapsulates close so this responsibility can be understood, tested, and changed independently.
    def close(self) -> None:
        """Perform close for the evaluation and quality-gate framework.

        Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        self._client.close()

    # Note: Orchestrates invoke, making this function a clear execution boundary for learners and tests.
    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        """Perform invoke for the evaluation and quality-gate framework.

        Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
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
        if response_model.metadata.sql_rows and not any(
            chunk.source == "database query" for chunk in chunks
        ):
            chunks.append(
                RetrievedChunk(
                    text=(
                        "Database evidence for the quantitative part of this question: "
                        f"{question}\nSQL Results:\n"
                    )
                    + json.dumps(response_model.metadata.sql_rows, indent=2, default=str),
                    source="database query",
                    score=1.0,
                    retrieval_score=1.0,
                )
            )
        return response_model, chunks

    # Note: Encapsulates bootstrap token so this responsibility can be understood, tested, and changed independently.
    def _bootstrap_token(self) -> str:
        """Support the evaluation and quality-gate framework by performing bootstrap token.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
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

    # Note: Encapsulates auth headers so this responsibility can be understood, tested, and changed independently.
    def _auth_headers(self) -> dict[str, str]:
        """Support the evaluation and quality-gate framework by performing auth headers.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        return {"Authorization": f"Bearer {self._token}"}

    # Note: Encapsulates decode json so this responsibility can be understood, tested, and changed independently.
    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        """Support the evaluation and quality-gate framework by performing decode json.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        try:
            return response.json()
        except Exception:
            return response.text

    # Note: Encapsulates detail text so this responsibility can be understood, tested, and changed independently.
    @staticmethod
    def _detail_text(payload: Any) -> str:
        """Support the evaluation and quality-gate framework by performing detail text.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
        return str(payload)


# Note: Fixture invoker is part of the evaluation and quality-gate framework.
class FixtureInvoker(Invoker):
    """Deterministic invoker for CI-safe eval smoke runs."""

    # Note: Initializes this component so its dependencies and runtime state are explicit.
    def __init__(self, goldens: list[Golden]):
        """Initialize init dependencies and runtime state.

        Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self._goldens_by_question = {golden.question: golden for golden in goldens}

    # Note: Orchestrates invoke, making this function a clear execution boundary for learners and tests.
    def invoke(
        self,
        question: str,
        flags: dict,
        intent: str,
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        """Perform invoke for the evaluation and quality-gate framework.

        Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
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
            "clarification": "clarification",
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
            "needs_clarification": intent == "clarification",
        }

        response = ChatResponse(
            answer=self._answer_text(golden),
            sources=sources,
            confidence=0.95,
            cache_hit=False,
            metadata=metadata,
        )
        return response, chunks

    # Note: Encapsulates answer text so this responsibility can be understood, tested, and changed independently.
    def _answer_text(self, golden: Golden) -> str:
        """Support the evaluation and quality-gate framework by performing answer text.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        keywords = ", ".join(golden.golden_answer_keywords)
        if golden.intent == "sql":
            return f"Mock SQL answer for {golden.id}: {keywords}."
        if golden.intent == "hybrid":
            return f"Mock hybrid answer for {golden.id}: {keywords}."
        if golden.intent == "web_fallback":
            return f"Mock web fallback answer for {golden.id}: {keywords}."
        if golden.intent == "clarification":
            return f"Please clarify the target for {golden.id}: {keywords}."
        return f"Mock RAG answer for {golden.id}: {keywords}."

    # Note: Encapsulates chunk text so this responsibility can be understood, tested, and changed independently.
    def _chunk_text(self, golden: Golden, source: str) -> str:
        """Support the evaluation and quality-gate framework by performing chunk text.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        keywords = ", ".join(golden.golden_answer_keywords)
        return (
            f"Fixture context for {golden.id} from {source}. "
            f"Question: {golden.question} "
            f"Relevant terms: {keywords}."
        )
