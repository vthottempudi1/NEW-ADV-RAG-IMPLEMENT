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

    service = IngestionService()
    return service.ingest_bytes(file.filename, content)
