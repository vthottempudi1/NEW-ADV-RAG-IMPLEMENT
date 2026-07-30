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


def _probe_postgres() -> None:
    """Execute a bounded, read-only PostgreSQL connectivity check."""
    with psycopg2.connect(settings.database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()


def _probe_qdrant() -> None:
    """Verify that Qdrant can return metadata for the configured collection."""
    get_client().get_collection(settings.qdrant_collection)


def _probe_redis() -> None:
    """Verify that the configured distributed Redis cache responds to PING."""
    client = query_cache._redis_client
    if client is None:
        raise RuntimeError("redis client unavailable")
    client.ping()


def _probe_s3() -> None:
    """Verify access to the configured S3 document-storage bucket."""
    storage = S3Storage()
    storage.client.head_bucket(Bucket=storage.bucket)


async def _run_dependency_probe(
    name: str,
    probe: Callable[[], None],
    *,
    timeout_seconds: float = 4.0,
) -> tuple[str, dict[str, Any]]:
    """Run a blocking probe callable in a worker thread under a timeout.

    Any exception (including a timeout) is caught and logged, never raised, so
    one failing dependency cannot take down the health check as a whole.
    Returns ``(name, {"status": "connected" | "unavailable", "latency_ms": float})``.
    """
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


class CacheClearRequest(BaseModel):
    """Request body for ``POST /admin/cache/clear``.

    ``tier`` selects which cache tier to clear (or ``"all"``). Depending on the
    tier, one of ``question``, ``sql``, or ``text`` must also be supplied to
    identify the specific cache entry to invalidate; ``cache_context`` provides
    extra keying context for the ``rag_answer`` tier. ``reset_stats`` only
    applies when clearing the ``"all"`` scope.
    """
    tier: Literal["all", "intent", "rag_answer", "sql_gen", "sql_result", "embedding"] = "all"
    question: str | None = None
    sql: str | None = None
    text: str | None = None
    cache_context: dict[str, Any] | None = None
    reset_stats: bool = True


@router.get("/health")
async def health_check(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Report connectivity and latency for all external dependencies.

    Runs the Postgres, Qdrant, Redis, and S3 probes concurrently (each bounded
    by its own timeout in ``_run_dependency_probe``). Overall ``status`` is
    ``"ok"`` if every dependency is connected, ``"degraded"`` if only the
    non-critical ones (Redis/S3) are down, and ``"unhealthy"`` if either
    critical dependency (Postgres or Qdrant) is unreachable. Also reports the
    active Qdrant collection name when Qdrant is reachable.
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


@router.get("/cache/stats")
async def cache_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Return hit/miss statistics for the query cache."""
    return query_cache.stats()


@router.get("/runtime-info")
async def runtime_info(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Return process/module diagnostics useful for confirming which code is deployed.

    Includes the working directory, the on-disk paths of ``app.main`` and
    ``app.rag.service``, the RAG cache schema version, the Python executable,
    and the first few ``sys.path`` entries.
    """
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
    """Clear one cache tier, or all tiers, from the query cache.

    With ``tier="all"`` (the default when no body is sent), clears every
    tier and optionally resets stats. For a targeted tier, the matching
    identifying field on ``body`` (``question`` for intent/rag_answer/sql_gen,
    ``sql`` for sql_result, ``text`` for embedding) is required and a 400 is
    raised if it's missing.
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


@router.get("/budgets")
async def budget_stats(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Return the configured daily per-user token budget and current usage."""
    return {
        "max_tokens_per_user_daily": settings.max_tokens_per_user_daily,
        "usage": get_budget_usage(),
    }


@router.post("/budgets/clear")
async def clear_budgets(user: User = Depends(require_admin)) -> dict[str, str]:
    """Reset all tracked per-user token budget usage."""
    clear_budget_usage()
    return {"status": "ok"}


@router.get("/rate-limits/{username}")
async def rate_limit_stats(
    username: str,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return the current request count and configured limit/window for ``username``."""
    return {
        "username": username,
        "count_in_window": get_rate_limit_count(username),
        "window_seconds": settings.rate_limit_window_seconds,
        "limit": settings.rate_limit_requests,
    }
