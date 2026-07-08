import logging
import sys
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router


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


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.exception_handler(HTTPException)
async def handled_http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
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
