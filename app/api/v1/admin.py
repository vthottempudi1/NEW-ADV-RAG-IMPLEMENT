import asyncio
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any, Literal

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.main as main_module
import app.rag.service as rag_service_module
from app.caching.query_cache import query_cache
from app.config import settings
from app.middleware.auth import User, require_admin

#from app.middleware.auth import User, require_admin
from app.middleware.rate_limiter import get_rate_limit_count
from app.rag.vector_store import get_client
from app.security.token_budget import clear_budget_usage, get_budget_usage
from app.storage.s3_storage import S3Storage

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# Learner Note: The PostgreSQL probe verifies the structured-data dependency without reading data.
def _probe_postgres() -> None:
    """Execute a bounded, read-only PostgreSQL connectivity check."""
    with psycopg2.connect(settings.database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()


# Learner Note: The Qdrant probe confirms that the configured release collection is available.
def _probe_qdrant() -> None:
    """Verify that Qdrant can return metadata for the configured collection."""
    get_client().get_collection(settings.qdrant_collection)


# Learner Note: Redis is optional for correctness but its availability affects cache performance.
def _probe_redis() -> None:
    """Verify that the configured distributed Redis cache responds to PING."""
    client = query_cache._redis_client
    if client is None:
        raise RuntimeError("redis client unavailable")
    client.ping()


# Learner Note: The S3 probe checks bucket access without listing or downloading private objects.
def _probe_s3() -> None:
    """Verify access to the configured S3 document-storage bucket."""
    storage = S3Storage()
    storage.client.head_bucket(Bucket=storage.bucket)


# Learner Note: Every dependency probe has the same safe status and latency response contract.
async def _run_dependency_probe(
    name: str,
    probe: Callable[[], None],
    *,
    timeout_seconds: float = 4.0,
) -> tuple[str, dict[str, Any]]:
    """Run one blocking dependency probe in a worker thread with a strict timeout."""
    started_at = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.to_thread(probe), timeout=timeout_seconds)
        status = "connected"
    except Exception as exc:
        status = "unavailable"
        logger.warning("dependency_probe_failed dependency=%s error=%s", name, type(exc).__name__)
    return name, {
        "status": status,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }


# Learner Note: Cache clear request is part of the versioned HTTP API boundary.
class CacheClearRequest(BaseModel):
    """Represent cache clear request within the versioned HTTP API boundary.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    tier: Literal["all", "intent", "rag_answer", "sql_gen", "sql_result", "embedding"] = "all"
    question: str | None = None
    sql: str | None = None
    text: str | None = None
    cache_context: dict[str, Any] | None = None
    reset_stats: bool = True


# Learner note: Encapsulates health check so this responsibility can be understood, tested, and changed independently.
@router.get("/health")
async def health_check(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Handle health check asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    probes = {
        "postgres": _probe_postgres,
        "qdrant": _probe_qdrant,
        "redis": _probe_redis,
        "s3": _probe_s3,
    }
    dependencies = dict(
        await asyncio.gather(
            *(_run_dependency_probe(name, probe) for name, probe in probes.items())
        )
    )
    critical_connected = all(
        dependencies[name]["status"] == "connected"
        for name in ("postgres", "qdrant")
    )
    all_connected = all(
        result["status"] == "connected" for result in dependencies.values()
    )
    overall_status = "ok" if all_connected else "degraded" if critical_connected else "unhealthy"

    return {
        "status": overall_status,
        "dependencies": dependencies,
        "active_collection": (
            settings.qdrant_collection
            if dependencies["qdrant"]["status"] == "connected"
            else None
        ),
    }


# Learner note: Encapsulates cache stats so this responsibility can be understood, tested, and changed independently.
@router.get("/cache/stats")
async def cache_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Handle cache stats asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    return query_cache.stats()


# Learner note: Encapsulates runtime info so this responsibility can be understood, tested, and changed independently.
@router.get("/runtime-info")
async def runtime_info(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Handle runtime info asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    return {
        "cwd": os.getcwd(),
        "main_file": getattr(main_module, "__file__", ""),
        "rag_service_file": getattr(rag_service_module, "__file__", ""),
        "rag_cache_schema_version": getattr(rag_service_module, "RAG_CACHE_SCHEMA_VERSION", None),
        "python_executable": sys.executable,
        "sys_path_head": sys.path[:5],
    }


# Learner note: Encapsulates cache clear so this responsibility can be understood, tested, and changed independently.
@router.post("/cache/clear")
async def cache_clear(
    body: CacheClearRequest | None = None,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Handle cache clear asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
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


# Learner note: Encapsulates budget stats so this responsibility can be understood, tested, and changed independently.
@router.get("/budgets")
async def budget_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Handle budget stats asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    return {
        "max_tokens_per_user_daily": settings.max_tokens_per_user_daily,
        "usage": get_budget_usage(),
    }


# Learner note: Clears clear budgets safely so tests and operations can restore a known state.
@router.post("/budgets/clear")
async def clear_budgets(user: User = Depends(require_admin)) -> dict[str, str]:
    """Handle clear budgets asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    clear_budget_usage()
    return {"status": "ok"}


# Learner note: Encapsulates rate limit stats so this responsibility can be understood, tested, and changed independently.
@router.get("/rate-limits/{username}")
async def rate_limit_stats(
    username: str,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Handle rate limit stats asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    return {
        "username": username,
        "count_in_window": get_rate_limit_count(username),
        "window_seconds": settings.rate_limit_window_seconds,
        "limit": settings.rate_limit_requests,
    }
