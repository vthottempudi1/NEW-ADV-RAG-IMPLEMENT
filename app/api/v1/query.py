import copy
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel
from qdrant_client.http.exceptions import UnexpectedResponse

from app.caching.query_cache import query_cache
from app.config import settings
from app.core.graph import build_hybrid_execution_result, build_sql_execution_result, graph
from app.middleware.auth import User, get_current_user
from app.middleware.rate_limiter import is_allowed_user
from app.models import ChatResponse, PendingSQLBlock, QueryRequest
from app.observability.costs import estimate_infra_cost_saved, format_usd
from app.rag.auto_retrieval import resolve_auto_retrieval
from app.rag.clarification import detect_clarification_need
from app.rag.conversation_context import rewrite_follow_up_question
from app.rag.router import classify_intent
from app.security.content_moderation import moderate_and_redact
from app.security.input_guard import check_input_safe
from app.security.input_restructuring import count_tokens, restructure_input
from app.security.output_validator import validate_output_safe
from app.security.token_budget import check_budget, consume_budget
from app.sql.pending_store import pending_sql_store
from app.sql.service import SQLService, SQLServiceError

router = APIRouter(tags=["query"])
sql_service = SQLService()


def _estimate_tokens(question: str) -> int:
    """Estimate the token cost of answering a question.

    Adds a reserved buffer for the model's output tokens on top of the
    tokenized length of the question, so budget checks account for both
    prompt and completion tokens.
    """
    return count_tokens(question) + settings.reserved_output_tokens


class SqlExecuteRequest(BaseModel):
    """Request body for approving or rejecting a pending SQL execution.

    ``query_id`` identifies the paused workflow (the LangGraph thread id
    returned as ``pending_sql.query_id`` from the ``/query`` endpoint), and
    ``approved`` indicates whether the human reviewer approved the generated
    SQL for execution.
    """
    query_id: str
    approved: bool


def _request_cache_context(body: QueryRequest) -> dict:
    """Extract the request fields that affect retrieval behavior into a cache key.

    Used to scope cached answers (and pending SQL approvals) to requests made
    with the same retrieval settings, so a cached answer generated with, say,
    reranking disabled is not served for a request that asked for reranking.
    """
    return {
        "top_k": body.top_k,
        "search_mode": body.search_mode,
        "enable_rerank": body.enable_rerank,
        "enable_hyde": body.enable_hyde,
        "enable_crag": body.enable_crag,
        "enable_self_reflective": body.enable_self_reflective,
    }


def _merge_auto_metadata(target: dict, decision) -> None:
    """Merge an auto-retrieval decision's metadata into ``target`` in place."""
    target.update(decision.metadata())


def _merge_auto_metadata_dict(target: dict, auto_metadata: dict | None) -> None:
    """Merge ``auto_metadata`` into ``target`` in place if it is non-empty."""
    if auto_metadata:
        target.update(auto_metadata)


def _as_float(value: object) -> float:
    """Coerce ``value`` to a float, returning 0.0 for ``None`` or unconvertible input."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _derive_cost_components(
    payload: dict,
    cache_context: dict | None = None,
) -> tuple[float, float]:
    """Return the (llm_cost_saved_usd, infra_cost_saved_usd) pair for a result payload.

    The LLM cost saved is read directly from the payload (falling back to the
    legacy ``cost_saved_usd`` key). The infra cost saved is also read from the
    payload, but if it comes back as zero it is instead estimated via
    ``estimate_infra_cost_saved`` using the result's route and cache context,
    since older/derived payloads may not carry a precomputed infra figure.
    Both values are rounded to 6 decimal places.
    """
    metadata = payload.get("metadata", {}) or {}
    route = str(metadata.get("route", "rag")).replace("_pending", "")
    llm_cost_saved_usd = _as_float(
        payload.get("llm_cost_saved_usd", payload.get("cost_saved_usd", 0.0))
    )
    infra_cost_saved_usd = _as_float(
        payload.get("infra_cost_saved_usd")
    )
    if infra_cost_saved_usd == 0.0:
        infra_cost_saved_usd = estimate_infra_cost_saved(
            route=route,
            cache_context=cache_context or payload.get("cache_context"),
            metadata=metadata,
        )
    return round(llm_cost_saved_usd, 6), round(infra_cost_saved_usd, 6)


def _display_saved_values(
    *,
    cache_hit: bool,
    llm_cost_saved_usd: float,
    infra_cost_saved_usd: float,
) -> tuple[str, str, str]:
    """Format the (llm, infra, total) cost-saved amounts as USD display strings.

    Returns all-zero strings when ``cache_hit`` is False, since cost savings
    only apply to answers served from cache rather than freshly generated.
    """
    if not cache_hit:
        zero = format_usd(0.0)
        return zero, zero, zero
    total = llm_cost_saved_usd + infra_cost_saved_usd
    return (
        format_usd(llm_cost_saved_usd),
        format_usd(infra_cost_saved_usd),
        format_usd(total),
    )


def _approved_cache_payload_from_result(
    result: dict,
    cache_context: dict | None = None,
) -> dict:
    """Build the payload stored in the query cache for an approved SQL/hybrid answer.

    Wraps the final answer, sources, confidence, and cost-saved figures
    together with ``cache_context`` so a future identical request (same
    question and retrieval settings) can be served from cache via
    ``_response_from_cached_payload`` instead of re-running SQL generation
    and approval.
    """
    llm_cost_saved_usd, infra_cost_saved_usd = _derive_cost_components(
        result,
        cache_context=cache_context,
    )
    return {
        "answer": result.get("final_answer", ""),
        "sources": result.get("sources", []),
        "confidence": result.get("confidence", 0.0),
        "cost_saved_usd": round(llm_cost_saved_usd + infra_cost_saved_usd, 6),
        "llm_cost_saved_usd": llm_cost_saved_usd,
        "infra_cost_saved_usd": infra_cost_saved_usd,
        "cache_context": cache_context or {},
        "metadata": result.get("metadata", {}) or {},
    }


def _response_from_cached_payload(payload: dict) -> ChatResponse:
    """Convert a cached query-cache payload into a ``ChatResponse``.

    Marks the response's metadata with ``cache_hit: True`` and recomputes the
    displayed cost-saved figures from the payload's stored cost components.
    """
    metadata = dict(payload.get("metadata", {}) or {})
    metadata["cache_hit"] = True
    llm_cost_saved_usd, infra_cost_saved_usd = _derive_cost_components(
        payload,
        cache_context=payload.get("cache_context"),
    )
    llm_cost_saved, infra_cost_saved, total_cost_saved = _display_saved_values(
        cache_hit=True,
        llm_cost_saved_usd=llm_cost_saved_usd,
        infra_cost_saved_usd=infra_cost_saved_usd,
    )
    return ChatResponse(
        answer=payload.get("answer", ""),
        sources=payload.get("sources", []),
        confidence=payload.get("confidence", 0.0),
        cache_hit=True,
        cost_saved=total_cost_saved,
        llm_cost_saved=llm_cost_saved,
        infra_cost_saved=infra_cost_saved,
        metadata=metadata,
    )


def _get_pending_sql_state_or_raise(query_id: str):
    """Look up the LangGraph checkpoint for ``query_id`` and confirm it is paused on SQL approval.

    Fetches the graph's persisted state snapshot for the given thread id and
    validates that it actually represents a workflow interrupted at the SQL
    approval step. Raises ``HTTPException`` with:

    - 500 if the checkpointer lookup itself fails.
    - 409 if no state exists at all for ``query_id`` (e.g. lost after a
      restart/redeploy since state is held in-memory).
    - 409 if state exists but the workflow is not currently interrupted
      (nothing pending approval).

    Returns the ``{"configurable": {"thread_id": query_id}}`` config dict
    usable to resume the graph via ``graph.invoke(Command(resume=...))``.
    """
    config = {"configurable": {"thread_id": query_id}}
    try:
        snapshot = graph.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "sql_approval_state_lookup_failed: unable to inspect the pending "
                f"workflow state for query_id={query_id}. {exc.__class__.__name__}: {exc}"
            ),
        ) from exc

    if not snapshot.values and not snapshot.next and not snapshot.interrupts:
        raise HTTPException(
            status_code=409,
            detail=(
                "sql_approval_context_missing: no resumable SQL approval context was "
                f"found for query_id={query_id}. This usually means the in-memory "
                "workflow state was lost after a restart or deployment. Re-run the "
                "original query to generate a new approval request."
            ),
        )

    if not snapshot.interrupts:
        raise HTTPException(
            status_code=409,
            detail=(
                "sql_approval_not_pending: the workflow for "
                f"query_id={query_id} is not currently waiting for SQL approval. "
                f"Pending nodes={list(snapshot.next)}. Re-run the original query if "
                "you need a new approval step."
            ),
        )

    return config


def _persist_pending_sql_or_raise(
    query_id: str,
    intent: str,
    question: str,
    request_context: dict,
    auto_metadata: dict,
) -> None:
    """Snapshot an interrupted graph run and save it as a pending SQL approval.

    Reads the graph's current state for ``query_id`` (the run that just
    raised the SQL-approval interrupt) and copies the generated SQL,
    explanation, and any RAG context (answer/sources/confidence/metadata for
    the hybrid route) into ``pending_sql_store``, alongside the original
    request context and auto-retrieval metadata. This lets ``execute_sql``
    resolve the approval later without needing to re-invoke the graph.
    Raises ``HTTPException(500)`` if the state snapshot cannot be read.
    """
    config = {"configurable": {"thread_id": query_id}}
    try:
        snapshot = graph.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "sql_pending_state_persist_failed: unable to inspect the interrupted "
                f"workflow state for query_id={query_id}. {exc.__class__.__name__}: {exc}"
            ),
        ) from exc

    values = snapshot.values or {}
    pending_sql_store.save_pending(
        query_id=query_id,
        intent=intent,
        question=question,
        generated_sql=values.get("generated_sql", ""),
        explanation=values.get("sql_explanation", ""),
        rag_answer=values.get("rag_answer"),
        rag_sources=values.get("rag_sources", []),
        rag_confidence=values.get("rag_confidence"),
        request_context=request_context,
        rag_metadata=values.get("rag_metadata", {}),
        auto_metadata=auto_metadata,
        cost_saved_usd=float(values.get("cost_saved_usd", 0.0))
        + float(values.get("sql_generation_cost_usd", 0.0)),
    )


def _resume_pending_sql_from_store(query_id: str, approved: bool) -> dict | None:
    """Resolve a pending SQL approval directly from ``pending_sql_store``, bypassing the graph checkpoint.

    Returns ``None`` if there is no pending record for ``query_id`` (the
    caller should then fall back to resuming the LangGraph checkpoint via
    ``_get_pending_sql_state_or_raise``/``graph.invoke(Command(...))``).

    If ``approved`` is False, marks the pending record as rejected and
    returns a result payload with an empty answer/no SQL rows, preserving the
    original RAG answer/sources for the hybrid route.

    If ``approved`` is True, executes the stored SQL via ``sql_service``,
    marks the pending record as approved, and builds the final result with
    ``build_hybrid_execution_result`` (hybrid route, merging in the prior RAG
    answer) or ``build_sql_execution_result`` (pure SQL route).
    """
    pending = pending_sql_store.get_pending(query_id)
    if not pending:
        return None
    auto_metadata = pending.get("auto_metadata", {}) or {}

    if not approved:
        pending_sql_store.resolve(query_id, status="rejected")
        if pending["intent"] == "hybrid":
            rag_metadata = pending.get("rag_metadata", {}) or {}
            result = {
                "sql_rows": [],
                "final_answer": "SQL query was not approved.",
                "sources": pending.get("rag_sources", []),
                "confidence": pending.get("rag_confidence") or 0.0,
                "cache_hit": False,
                "cost_saved_usd": float(pending.get("cost_saved_usd", 0.0)),
                "metadata": {
                    "route": "hybrid",
                    "retrieved_chunks": rag_metadata.get("retrieved_chunks", []),
                    "cache_hit": False,
                    "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
                    "reflection_score": rag_metadata.get("reflection_score"),
                    "refined_question": rag_metadata.get("refined_question"),
                    "retrieval_question": rag_metadata.get("retrieval_question"),
                    "crag_score": rag_metadata.get("crag_score"),
                    "crag_label": rag_metadata.get("crag_label"),
                    "crag_relevant_chunks": rag_metadata.get("crag_relevant_chunks"),
                    "crag_total_chunks": rag_metadata.get("crag_total_chunks"),
                    "crag_relevant_ratio": rag_metadata.get("crag_relevant_ratio"),
                    "crag_chunk_scores": rag_metadata.get("crag_chunk_scores", []),
                    "used_web_fallback": rag_metadata.get("used_web_fallback", False),
                    "sql_query": pending.get("generated_sql", ""),
                    "sql_rows": [],
                },
            }
            _merge_auto_metadata_dict(result["metadata"], auto_metadata)
            return result
        result = {
            "sql_rows": [],
            "final_answer": "SQL query was not approved.",
            "sources": [],
            "confidence": 0.0,
            "cache_hit": False,
            "metadata": {"route": "sql", "retrieved_chunks": []},
        }
        _merge_auto_metadata_dict(result["metadata"], auto_metadata)
        return result

    sql = pending["generated_sql"]
    rows = sql_service.execute_sql(sql)
    pending_sql_store.resolve(query_id, status="approved")
    if pending["intent"] == "hybrid":
        result = build_hybrid_execution_result(
            question=pending["question"],
            sql=sql,
            rows=rows,
            rag_sources=pending.get("rag_sources", []),
            rag_confidence=pending.get("rag_confidence") or 0.0,
            rag_metadata=pending.get("rag_metadata", {}) or {},
            cost_saved_usd=float(pending.get("cost_saved_usd", 0.0)),
        )
        _merge_auto_metadata_dict(result.setdefault("metadata", {}), auto_metadata)
        return result
    result = build_sql_execution_result(
        pending["question"],
        sql,
        rows,
        cost_saved_usd=float(pending.get("cost_saved_usd", 0.0)),
    )
    _merge_auto_metadata_dict(result.setdefault("metadata", {}), auto_metadata)
    return result


def _raise_query_exception(exc: Exception) -> None:
    """Translate an exception raised during graph execution into an ``HTTPException``.

    Maps ``SQLServiceError`` to its own status code/public detail, maps
    Qdrant's ``UnexpectedResponse`` to a 503 (with a dedicated message for
    403/permission errors), and falls back to a generic 500 for anything
    else. Always raises; never returns normally.
    """
    if isinstance(exc, SQLServiceError):
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.public_detail,
        ) from exc

    if isinstance(exc, UnexpectedResponse):
        status = getattr(exc, "status_code", None)
        if status == 403:
            raise HTTPException(
                status_code=503,
                detail=(
                    "retrieval_backend_forbidden: Qdrant Cloud rejected the request. "
                    "Verify the deployed Qdrant API key has data-query permissions and "
                    "that the target collection is populated."
                ),
            ) from exc
        raise HTTPException(
            status_code=503,
            detail=f"retrieval_backend_error: Qdrant returned status {status or 'unknown'}",
        ) from exc

    raise HTTPException(
        status_code=500,
        detail=f"query_failed: {exc.__class__.__name__}: {exc}",
    ) from exc


@router.post("/query", response_model=ChatResponse)
async def query(
    body: QueryRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """Answer a natural-language question, invoking the LangGraph RAG/SQL/hybrid workflow.

    This is the primary entry point of the query API. Given an authenticated
    ``user`` (via ``get_current_user``) and a ``QueryRequest`` body, it runs
    the request through a pipeline before touching the graph:

    1. Per-user rate limiting (``is_allowed_user``) -> 429 if exceeded.
    2. Token budget check (``check_budget`` against estimated question +
       reserved output tokens) -> 429 if the user's daily token budget is
       exhausted.
    3. Input restructuring/truncation and prompt-injection/safety screening
       (``restructure_input``, ``check_input_safe``) -> 400 if unsafe.
    4. Content moderation and redaction (``moderate_and_redact``) -> 400 if
       blocked.
    5. Follow-up question rewriting using conversation context
       (``rewrite_follow_up_question``).
    6. Clarification-need detection: if the (rewritten) question is
       ambiguous, returns a ``ChatResponse`` asking for clarification without
       touching the graph.
    7. Intent classification (``classify_intent`` -> "sql", "hybrid", or
       RAG-only) and auto-retrieval strategy resolution
       (``resolve_auto_retrieval``), which determines the graph flags (rerank,
       HyDE, CRAG, self-reflective, etc.) actually used.
    8. Query-cache lookup for SQL/hybrid intents: if an approved cached
       answer exists for this question (and cache context), it is returned
       directly (after output validation) without invoking the graph.
    9. Otherwise, invokes ``graph.invoke(...)`` with a fresh thread id as the
       checkpointer key. If the graph raises, the exception is translated via
       ``_raise_query_exception`` (SQL errors, Qdrant errors, or a generic
       500). If the graph pauses on a human-in-the-loop SQL approval
       interrupt (``"__interrupt__"`` in the result), the pending SQL and RAG
       context are persisted via ``_persist_pending_sql_or_raise`` and a
       ``ChatResponse`` with a populated ``pending_sql`` block is returned
       (to be resolved later via ``POST /query/sql/execute`` using the
       returned ``query_id``/thread id).
    10. On a normal (non-interrupted) result, builds the final
        ``ChatResponse`` (answer, sources, confidence, cost-saved figures),
        validates the output for safety (-> 500 if blocked), consumes the
        estimated token budget, and returns it.
    """
    allowed, _, _ = is_allowed_user(
        user.username,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    estimated = _estimate_tokens(body.question)
    ok, remaining = check_budget(
        user.username,
        estimated_tokens=estimated,
        max_tokens=settings.max_tokens_per_user_daily,
    )
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"Token budget exceeded. Remaining: {remaining}",
        )

    question, _ = restructure_input(body.question, settings.max_input_tokens)
    safe, reason = check_input_safe(question)
    if not safe:
        raise HTTPException(status_code=400, detail=f"input_blocked: {reason}")

    allowed, moderated_question, mod_reason = moderate_and_redact(question)
    if not allowed:
        raise HTTPException(status_code=400, detail=f"content_blocked: {mod_reason}")

    resolved_question, resolved_subject = rewrite_follow_up_question(
        moderated_question,
        [turn.model_dump() for turn in body.conversation_context],
    )

    clarification = detect_clarification_need(resolved_question)
    if clarification is not None:
        return ChatResponse(
            answer=clarification.prompt,
            sources=[],
            confidence=1.0,
            cache_hit=False,
            metadata={
                "route": "clarification",
                "retrieved_chunks": [],
                "requested_search_mode": body.search_mode,
                "resolved_search_mode": None,
                "auto_enabled": body.search_mode == "auto",
                "auto_strategy_reason": clarification.reason,
                "original_question": moderated_question,
                "resolved_question": resolved_question,
                "resolved_follow_up_subject": resolved_subject,
                "needs_clarification": True,
                "clarification_question": clarification.prompt,
                "clarification_reason": clarification.reason,
                "clarification_type": clarification.ambiguity_type,
            },
        )

    intent = classify_intent(resolved_question)
    auto_decision = resolve_auto_retrieval(
        question=resolved_question,
        search_mode=body.search_mode,
        enable_rerank=body.enable_rerank,
        enable_hyde=body.enable_hyde,
        enable_crag=body.enable_crag,
        enable_self_reflective=body.enable_self_reflective,
    )
    request_context = auto_decision.cache_context(body.top_k)

    cached_payload = None
    if intent == "sql":
        cached_payload = query_cache.get_approved_answer("sql", resolved_question)
    elif intent == "hybrid":
        cached_payload = query_cache.get_approved_answer(
            "hybrid",
            resolved_question,
            request_context,
        )
    if cached_payload is not None:
        cached_payload = copy.deepcopy(cached_payload)
        _merge_auto_metadata_dict(
            cached_payload.setdefault("metadata", {}),
            auto_decision.metadata(),
        )
        cached_payload["metadata"]["original_question"] = moderated_question
        cached_payload["metadata"]["resolved_question"] = resolved_question
        cached_payload["metadata"]["resolved_follow_up_subject"] = resolved_subject
        response = _response_from_cached_payload(cached_payload)
        safe_output, output_reason = validate_output_safe(response.answer)
        if not safe_output:
            raise HTTPException(status_code=500, detail=f"output_blocked: {output_reason}")
        consume_budget(user.username, estimated)
        return response

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph.invoke(
            {
                "question": resolved_question,
                "user_id": user.username,
                "flags": auto_decision.graph_flags(body.top_k),
            },
            config=config,
        )
    except Exception as exc:
        _raise_query_exception(exc)

    if "__interrupt__" in result:
        intr = result["__interrupt__"][0].value
        _persist_pending_sql_or_raise(
            thread_id,
            intent,
            resolved_question,
            request_context,
            auto_decision.metadata(),
        )
        return ChatResponse(
            answer="",
            sources=[],
            confidence=0.0,
            pending_sql=PendingSQLBlock(
                sql=intr.get("sql", ""),
                query_id=thread_id,
                explanation=intr.get("explanation", ""),
            ),
            metadata={
                "route": "hybrid_sql_pending" if intent == "hybrid" else "sql_pending",
                "retrieved_chunks": [],
                "cache_hit": False,
                **auto_decision.metadata(),
                "original_question": moderated_question,
                "resolved_question": resolved_question,
                "resolved_follow_up_subject": resolved_subject,
                "reflection_iterations": 0,
                "reflection_score": None,
                "refined_question": None,
                "retrieval_question": None,
                "crag_score": None,
                "crag_label": None,
                "crag_relevant_chunks": None,
                "crag_total_chunks": None,
                "crag_relevant_ratio": None,
                "crag_chunk_scores": [],
                "used_web_fallback": False,
            },
        )

    result_metadata = result.setdefault("metadata", {})
    _merge_auto_metadata(result_metadata, auto_decision)
    result_metadata["original_question"] = moderated_question
    result_metadata["resolved_question"] = resolved_question
    result_metadata["resolved_follow_up_subject"] = resolved_subject

    llm_cost_saved_usd, infra_cost_saved_usd = _derive_cost_components(
        result,
        cache_context=request_context,
    )
    llm_cost_saved, infra_cost_saved, total_cost_saved = _display_saved_values(
        cache_hit=bool(result.get("cache_hit", False)),
        llm_cost_saved_usd=llm_cost_saved_usd,
        infra_cost_saved_usd=infra_cost_saved_usd,
    )
    response = ChatResponse(
        answer=result.get("final_answer", ""),
        sources=result.get("sources", []),
        confidence=result.get("confidence", 0.0),
        cache_hit=result.get("cache_hit", False),
        cost_saved=total_cost_saved,
        llm_cost_saved=llm_cost_saved,
        infra_cost_saved=infra_cost_saved,
        metadata=result.get("metadata", {}),
    )
    safe_output, output_reason = validate_output_safe(response.answer)
    if not safe_output:
        raise HTTPException(status_code=500, detail=f"output_blocked: {output_reason}")

    consume_budget(user.username, estimated)
    return response


@router.post("/query/sql/execute", response_model=ChatResponse)
async def execute_sql(
    body: SqlExecuteRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """Approve or reject a previously generated SQL query and return the final answer.

    This resumes the human-in-the-loop workflow paused by ``POST /query``
    when SQL generation required approval. ``body.query_id`` identifies the
    paused run and ``body.approved`` is the reviewer's decision.

    Resolution takes one of two paths:

    - Fast path: if ``pending_sql_store`` still has the record for
      ``query_id``, ``_resume_pending_sql_from_store`` resolves the approval
      directly (running the SQL via ``sql_service`` if approved, or building
      a rejection result otherwise) without touching the LangGraph
      checkpoint.
    - Fallback path: if the pending-sql record is gone (e.g. app restart) but
      the graph checkpoint is still available, ``_get_pending_sql_state_or_raise``
      validates the checkpoint is actually paused on this interrupt (raising
      404/409/500 ``HTTPException``s otherwise), and the graph is resumed via
      ``graph.invoke(Command(resume={"approved": body.approved}), config=...)``.
      Exceptions from the resumed graph are translated via
      ``_raise_query_exception``.

    In both paths, the final answer's cost-saved figures are computed, the
    output is safety-validated (-> 500 if blocked), and if the query was
    approved, the resulting answer is written to the query cache
    (``query_cache.set_approved_answer``) so identical future requests can be
    served from cache. Returns the final ``ChatResponse``.
    """
    pending = pending_sql_store.get_pending(body.query_id)
    stored_result = _resume_pending_sql_from_store(body.query_id, body.approved)
    if stored_result is not None:
        stored_cache_context = pending.get("request_context") if pending is not None else None
        if pending is not None:
            _merge_auto_metadata_dict(
                stored_result.setdefault("metadata", {}),
                pending.get("auto_metadata"),
            )
        llm_cost_saved_usd, infra_cost_saved_usd = _derive_cost_components(
            stored_result,
            cache_context=stored_cache_context,
        )
        llm_cost_saved, infra_cost_saved, total_cost_saved = _display_saved_values(
            cache_hit=bool(stored_result.get("cache_hit", False)),
            llm_cost_saved_usd=llm_cost_saved_usd,
            infra_cost_saved_usd=infra_cost_saved_usd,
        )
        response = ChatResponse(
            answer=stored_result.get("final_answer", "SQL query was not approved."),
            sources=stored_result.get("sources", []),
            confidence=stored_result.get("confidence", 0.0),
            cache_hit=stored_result.get("cache_hit", False),
            cost_saved=total_cost_saved,
            llm_cost_saved=llm_cost_saved,
            infra_cost_saved=infra_cost_saved,
            metadata=stored_result.get("metadata", {}),
        )
        safe_output, output_reason = validate_output_safe(response.answer)
        if not safe_output:
            raise HTTPException(status_code=500, detail=f"output_blocked: {output_reason}")
        if body.approved and pending is not None:
            route = "hybrid" if pending["intent"] == "hybrid" else "sql"
            query_cache.set_approved_answer(
                route,
                pending["question"],
                _approved_cache_payload_from_result(
                    stored_result,
                    pending.get("request_context") if route == "hybrid" else None,
                ),
                pending.get("request_context") if route == "hybrid" else None,
            )
        return response

    config = _get_pending_sql_state_or_raise(body.query_id)

    try:
        result = graph.invoke(
            Command(resume={"approved": body.approved}),
            config=config,
        )
    except Exception as exc:
        _raise_query_exception(exc)

    resume_cache_context = pending.get("request_context") if pending is not None else None
    if pending is not None:
        _merge_auto_metadata_dict(
            result.setdefault("metadata", {}),
            pending.get("auto_metadata"),
        )
    llm_cost_saved_usd, infra_cost_saved_usd = _derive_cost_components(
        result,
        cache_context=resume_cache_context,
    )
    llm_cost_saved, infra_cost_saved, total_cost_saved = _display_saved_values(
        cache_hit=bool(result.get("cache_hit", False)),
        llm_cost_saved_usd=llm_cost_saved_usd,
        infra_cost_saved_usd=infra_cost_saved_usd,
    )
    response = ChatResponse(
        answer=result.get("final_answer", "SQL query was not approved."),
        sources=result.get("sources", []),
        confidence=result.get("confidence", 0.0),
        cache_hit=result.get("cache_hit", False),
        cost_saved=total_cost_saved,
        llm_cost_saved=llm_cost_saved,
        infra_cost_saved=infra_cost_saved,
        metadata=result.get("metadata", {}),
    )
    safe_output, output_reason = validate_output_safe(response.answer)
    if not safe_output:
        raise HTTPException(status_code=500, detail=f"output_blocked: {output_reason}")

    if body.approved and pending is not None:
        route = "hybrid" if pending["intent"] == "hybrid" else "sql"
        query_cache.set_approved_answer(
            route,
            pending["question"],
            _approved_cache_payload_from_result(
                result,
                pending.get("request_context") if route == "hybrid" else None,
            ),
            pending.get("request_context") if route == "hybrid" else None,
        )

    return response
