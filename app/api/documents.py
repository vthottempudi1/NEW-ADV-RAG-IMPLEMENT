from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.middleware.auth import User, require_admin
from app.services.ingestion_service import IngestionService


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
) -> dict:
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
