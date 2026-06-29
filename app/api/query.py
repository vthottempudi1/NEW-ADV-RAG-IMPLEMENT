from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.graph import graph
from app.middleware.auth import User, get_current_user
from app.middleware.rate_limiter import is_allowed_user
from app.models import ChatResponse, QueryRequest
from app.security.input_restructuring import count_tokens, restructure_input
from app.security.token_budget import check_budget, consume_budget
from app.security.content_moderation import moderate_and_redact
from app.security.input_guard import check_input_safe
from app.security.output_validator import validate_output_safe


router = APIRouter(tags=["query"])


def _estimate_tokens(question: str) -> int:
    return count_tokens(question) + settings.reserved_output_tokens


@router.post("/query", response_model=ChatResponse)
async def query(
    body: QueryRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
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

    result = graph.invoke(
        {
            "question": moderated_question,
            "user_id": user.username,
            "flags": {
                "top_k": body.top_k,
                "search_mode": body.search_mode,
                "enable_rerank": body.enable_rerank,
                "enable_hyde": body.enable_hyde,
                "enable_crag": body.enable_crag,
                "enable_self_reflective": body.enable_self_reflective,
            },
        }
    )

    response = ChatResponse(
        answer=result.get("final_answer", ""),
        sources=result.get("sources", []),
        confidence=result.get("confidence", 0.0),
        cache_hit=result.get("cache_hit", False),
        metadata=result.get("metadata", {}),
    )
    safe_output, output_reason = validate_output_safe(response.answer)
    if not safe_output:
        raise HTTPException(status_code=500, detail=f"output_blocked: {output_reason}")

    consume_budget(user.username, estimated)
    return response