from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ingestion.service import IngestionService
from app.middleware.auth import User, require_admin

router = APIRouter(prefix="/documents", tags=["documents"])


# Learner note: Encapsulates upload document so this responsibility can be understood, tested, and changed independently.
@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
) -> dict:
    """Handle upload document asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
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
