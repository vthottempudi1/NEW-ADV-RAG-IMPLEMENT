from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router


app = FastAPI(
    title="New Enterprise Advanced RAG",
    version="0.1.3",
)

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(query_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}