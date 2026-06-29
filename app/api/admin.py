from typing import Any

from fastapi import APIRouter, Depends


from app.config import settings
from app.services.query_cache_service import query_cache
from app.services.vector_store import get_client
from app.middleware.auth import User, require_admin
#from app.middleware.auth import User, require_admin
from app.middleware.rate_limiter import get_rate_limit_count
from app.security.token_budget import clear_budget_usage, get_budget_usage


router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.post("/cache/clear")
async def cache_clear(user: User = Depends(require_admin)) -> dict[str, Any]:
    cleared = query_cache.clear()
    return {"status": "ok", "cleared": cleared}


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