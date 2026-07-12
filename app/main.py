import logging
import sys
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.query import router as query_router

app = FastAPI(
    title="New Enterprise Advanced RAG",
    version="0.1.6",
)

logger = logging.getLogger(__name__)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(query_router)

# Enterprise clients can migrate to an explicitly versioned URL while the legacy
# routes remain available for the currently deployed frontend and API consumers.
app.include_router(admin_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(query_router, prefix="/api/v1")


# Learner note: Correlates and times each request so production failures and latency can be traced in CloudWatch.
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Handle attach request id asynchronously within the enterprise RAG application.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "request_complete method=%s path=%s status_code=%s duration_ms=%.2f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


# Learner note: Encapsulates health so this responsibility can be understood, tested, and changed independently.
@app.get("/health")
async def health() -> dict[str, str]:
    """Handle health asynchronously within the enterprise RAG application.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    return {"status": "ok", "version": app.version}


# Learner note: Encapsulates handled http exception handler so this responsibility can be understood, tested, and changed independently.
@app.exception_handler(HTTPException)
async def handled_http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Handle handled http exception handler asynchronously within the enterprise RAG application.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    content = {
        "detail": exc.detail,
        "path": request.url.path,
        "method": request.method,
        "request_id": request_id,
        "status_code": exc.status_code,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers={"x-request-id": request_id},
    )


# Learner note: Encapsulates unhandled exception handler so this responsibility can be understood, tested, and changed independently.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exception handler asynchronously within the enterprise RAG application.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "Unhandled backend error on %s %s request_id=%s",
        request.method,
        request.url.path,
        request_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"internal_server_error: {exc.__class__.__name__}: {exc}",
            "path": request.url.path,
            "method": request.method,
            "request_id": request_id,
            "status_code": 500,
        },
        headers={"x-request-id": request_id},
    )
