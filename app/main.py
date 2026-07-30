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

# Legacy aliases remain callable by the deployed Streamlit client and older API consumers, but
# they are hidden from OpenAPI so Swagger presents one canonical versioned API instead of duplicate
# Admin, Auth, Documents, and Query operations.
app.include_router(admin_router, include_in_schema=False)
app.include_router(auth_router, include_in_schema=False)
app.include_router(documents_router, include_in_schema=False)
app.include_router(query_router, include_in_schema=False)

# Enterprise clients can migrate to an explicitly versioned URL while the legacy
# routes remain available for the currently deployed frontend and API consumers.
app.include_router(admin_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(query_router, prefix="/api/v1")


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """HTTP middleware that stamps every request/response with a correlation ID and logs completion.

    Reuses the caller-supplied `x-request-id` header if present, otherwise generates
    a new UUID4. Stores it on `request.state.request_id` (so route handlers and
    exception handlers can reference it), echoes it back as an `x-request-id`
    response header, and logs method/path/status/duration on completion. This is
    the mechanism that lets a single request be traced end-to-end across logs
    (e.g. in CloudWatch).
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


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness/readiness probe endpoint. Returns `{"status": "ok", "version": <app version>}`."""
    return {"status": "ok", "version": app.version}


@app.exception_handler(HTTPException)
async def handled_http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Render any raised HTTPException as a consistent JSON error body.

    Includes the exception's detail/status code alongside the request path, method,
    and correlation ID (falling back to "unknown" if `attach_request_id` never ran
    for this request), and echoes the `x-request-id` response header.
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for any exception not already handled, so the API never leaks a raw 500 with no context.

    Logs the full traceback (via `logger.exception`) tagged with method/path/request
    ID for debugging, then returns a 500 JSON body containing the exception's class
    name and message plus the request's correlation ID. This is the last line of
    defense preventing an unhandled error from crashing the worker or returning an
    opaque response.
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
