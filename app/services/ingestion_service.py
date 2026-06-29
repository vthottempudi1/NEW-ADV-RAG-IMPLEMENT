from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

#from docx import settings
from app.config import settings

from app.models import RetrievedChunk
from app.services.doc_cache_service import DocCacheService
from app.services.document_processor import DocumentProcessor
from app.services.embedding_service import embed_texts
from app.services.vector_store import upsert_chunks



class IngestionService:
    def __init__(self):
        self.doc_cache = DocCacheService()
        self.processor = DocumentProcessor()

    def ingest_file(self, file_path: str) -> dict:
        path = Path(file_path)
        content_hash = self.doc_cache.compute_file_hash(path)

        if self._already_indexed(content_hash):
            metadata = self.doc_cache.get_metadata(content_hash) or {}
            return {
                "status": "skipped",
                "reason": "already_indexed",
                "content_hash": content_hash,
                "metadata": metadata,
            }

        chunks_meta = self.processor.process_document(str(path))
        chunks = self._build_chunk_models(chunks_meta)
        texts = [chunk.text for chunk in chunks]
        embeddings = embed_texts(texts)
        upsert_chunks(chunks, embeddings)

        metadata = {
            "content_hash": content_hash,
            "filename": path.name,
            "source_path": str(path),
            "chunks_indexed": len(chunks),
            "page_count": self._page_count(chunks_meta),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "vector_backend": "qdrant",
            "collection_name": settings.qdrant_collection,
        }
        self.doc_cache.set_metadata(content_hash, metadata)

        return {
            "status": "indexed",
            "content_hash": content_hash,
            "chunks_indexed": len(chunks),
            "metadata": metadata,
        }

    def ingest_bytes(self, filename: str, content: bytes) -> dict:
        content_hash = self.doc_cache.compute_content_hash(content)

        if self._already_indexed(content_hash):
            metadata = self.doc_cache.get_metadata(content_hash) or {}
            return {
                "status": "skipped",
                "reason": "already_indexed",
                "content_hash": content_hash,
                "metadata": metadata,
            }

        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            chunks_meta = self.processor.process_document(temp_path)
            chunks = self._build_chunk_models(chunks_meta)
            texts = [chunk.text for chunk in chunks]
            embeddings = embed_texts(texts)
            upsert_chunks(chunks, embeddings)

            metadata = {
                "content_hash": content_hash,
                "filename": filename,
                "source_path": temp_path,
                "chunks_indexed": len(chunks),
                "page_count": self._page_count(chunks_meta),
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "vector_backend": "qdrant",
                "collection_name": settings.qdrant_collection,
            }
            self.doc_cache.set_metadata(content_hash, metadata)

            return {
                "status": "indexed",
                "content_hash": content_hash,
                "chunks_indexed": len(chunks),
                "metadata": metadata,
            }
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _already_indexed(self, content_hash: str) -> bool:
        return self.doc_cache.exists(content_hash)

    def _build_chunk_models(self, chunks_meta: list[dict]) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                text=item["text"],
                source=item.get("source_name") or item.get("source", "unknown"),
            )
            for item in chunks_meta
            if item.get("text")
        ]

    def _page_count(self, chunks_meta: list[dict]) -> int:
        pages = {
            item.get("page_number")
            for item in chunks_meta
            if item.get("page_number") is not None
        }
        return len(pages)