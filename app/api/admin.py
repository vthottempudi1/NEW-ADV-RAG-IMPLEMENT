import os
import sys
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.main as main_module
from app.config import settings
import app.services.rag_service as rag_service_module
from app.services.query_cache_service import query_cache
from app.services.vector_store import get_client
from app.middleware.auth import User, require_admin
#from app.middleware.auth import User, require_admin
from app.middleware.rate_limiter import get_rate_limit_count
from app.security.token_budget import clear_budget_usage, get_budget_usage


router = APIRouter(prefix="/admin", tags=["admin"])


class CacheClearRequest(BaseModel):
    tier: Literal["all", "intent", "rag_answer", "sql_gen", "sql_result", "embedding"] = "all"
    question: str | None = None
    sql: str | None = None
    text: str | None = None
    cache_context: dict[str, Any] | None = None
    reset_stats: bool = True


@router.get("/health")
async def health_check(user: User = Depends(require_admin)) -> dict[str, Any]:
    qdrant_ok = False
    qdrant_collection = None

    try:
        client = get_client()
        collections = client.get_collections().collections
        qdrant_ok = True
        qdrant_collection = settings.qdrant_collection if any(
            c.name == settings.qdrant_collection for c in collections
        ) else None
    except Exception as exc:
        qdrant_collection = {"error": str(exc)}

    return {
        "status": "ok" if qdrant_ok else "degraded",
        "qdrant": qdrant_ok,
        "active_collection": qdrant_collection,
    }


@router.get("/cache/stats")
async def cache_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    return query_cache.stats()


@router.get("/runtime-info")
async def runtime_info(user: User = Depends(require_admin)) -> dict[str, Any]:
    return {
        "cwd": os.getcwd(),
        "main_file": getattr(main_module, "__file__", ""),
        "rag_service_file": getattr(rag_service_module, "__file__", ""),
        "rag_cache_schema_version": getattr(rag_service_module, "RAG_CACHE_SCHEMA_VERSION", None),
        "python_executable": sys.executable,
        "sys_path_head": sys.path[:5],
    }


@router.post("/cache/clear")
async def cache_clear(
    body: CacheClearRequest | None = None,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    body = body or CacheClearRequest()

    if body.tier == "all":
        cleared = query_cache.clear(reset_stats=body.reset_stats)
        return {"status": "ok", "scope": "all", "cleared": cleared}

    if body.tier == "intent":
        if not body.question:
            raise HTTPException(status_code=400, detail="question is required for intent cache clear")
        cleared = query_cache.clear_intent(body.question)
    elif body.tier == "rag_answer":
        if not body.question:
            raise HTTPException(status_code=400, detail="question is required for rag_answer cache clear")
        cleared = query_cache.clear_rag_answer(body.question, body.cache_context)
    elif body.tier == "sql_gen":
        if not body.question:
            raise HTTPException(status_code=400, detail="question is required for sql_gen cache clear")
        cleared = query_cache.clear_sql_generation(body.question)
    elif body.tier == "sql_result":
        if not body.sql:
            raise HTTPException(status_code=400, detail="sql is required for sql_result cache clear")
        cleared = query_cache.clear_sql_result(body.sql)
    else:
        if not body.text:
            raise HTTPException(status_code=400, detail="text is required for embedding cache clear")
        cleared = query_cache.clear_embedding(body.text)

    return {"status": "ok", "scope": "targeted", "cleared": cleared}


@router.get("/budgets")
async def budget_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    return {
        "max_tokens_per_user_daily": settings.max_tokens_per_user_daily,
        "usage": get_budget_usage(),
    }


@router.post("/budgets/clear")
async def clear_budgets(user: User = Depends(require_admin)) -> dict[str, str]:
    clear_budget_usage()
    return {"status": "ok"}


@router.get("/rate-limits/{username}")
async def rate_limit_stats(
    username: str,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    return {
        "username": username,
        "count_in_window": get_rate_limit_count(username),
        "window_seconds": settings.rate_limit_window_seconds,
        "limit": settings.rate_limit_requests,
    }
