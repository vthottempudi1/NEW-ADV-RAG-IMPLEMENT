from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ingestion.service import IngestionService
from app.middleware.auth import User, require_admin

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
) -> dict:
    """Ingest an uploaded document into the RAG corpus.

    Requires admin auth (enforced via require_admin). Rejects requests with no
    filename or an empty file body with a 400, reads the full upload into
    memory, then hands the bytes to IngestionService.ingest_bytes for parsing,
    chunking, embedding, and storage. Any HTTPException raised during ingestion
    propagates unchanged; any other exception is wrapped and re-raised as a 500
    with the original exception type and message in the detail.

    Returns the dict produced by IngestionService.ingest_bytes (ingestion result
    summary, e.g. chunk/document counts).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        service = IngestionService()
        return service.ingest_bytes(file.filename, content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"upload_failed: {exc.__class__.__name__}: {exc}",
        ) from exc
