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
from app.storage.storage_backend import get_storage_backend



class IngestionService:
    def __init__(self):
        self.doc_cache = DocCacheService()
        self.processor = DocumentProcessor()
        self.storage = get_storage_backend()

    def _storage_key(self, content_hash: str, filename: str) -> str:
        safe_name = Path(filename).name or "uploaded.bin"
        return f"documents/{content_hash}/{safe_name}"

    def _normalize_chunk_sources(
        self,
        chunks_meta: list[dict],
        *,
        filename: str,
        source_path: str,
    ) -> list[dict]:
        normalized: list[dict] = []
        for item in chunks_meta:
            updated = dict(item)
            updated["source"] = filename
            updated["source_name"] = filename
            updated["source_path"] = source_path
            normalized.append(updated)
        return normalized

    def ingest_file(self, file_path: str, *, force_reindex: bool = False) -> dict:
        path = Path(file_path)
        content_hash = self.doc_cache.compute_file_hash(path)
        content = path.read_bytes()
        storage_key = self._storage_key(content_hash, path.name)
        self.storage.save_bytes(storage_key, content)
        storage_url = self.storage.url_for(storage_key)

        if not force_reindex and self._already_indexed(content_hash):
            metadata = self.doc_cache.get_metadata(content_hash) or {}
            return {
                "status": "skipped",
                "reason": "already_indexed",
                "content_hash": content_hash,
                "metadata": metadata,
                "storage_backend": settings.storage_backend,
                "storage_key": storage_key,
                "storage_url": storage_url,
            }

        chunks_meta = self.processor.process_document(str(path))
        chunks_meta = self._normalize_chunk_sources(
            chunks_meta,
            filename=path.name,
            source_path=str(path),
        )
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
            "storage_backend": settings.storage_backend,
            "storage_key": storage_key,
            "storage_url": storage_url,
        }
        self.doc_cache.set_metadata(content_hash, metadata)

        return {
            "status": "indexed",
            "content_hash": content_hash,
            "chunks_indexed": len(chunks),
            "metadata": metadata,
        }

    def ingest_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        force_reindex: bool = False,
    ) -> dict:
        content_hash = self.doc_cache.compute_content_hash(content)

        if not force_reindex and self._already_indexed(content_hash):
            metadata = self.doc_cache.get_metadata(content_hash) or {}
            return {
                "status": "skipped",
                "reason": "already_indexed",
                "content_hash": content_hash,
                "metadata": metadata,
            }

        suffix = Path(filename).suffix
        storage_key = self._storage_key(content_hash, filename)
        self.storage.save_bytes(storage_key, content)
        storage_url = self.storage.url_for(storage_key)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            chunks_meta = self.processor.process_document(temp_path)
            chunks_meta = self._normalize_chunk_sources(
                chunks_meta,
                filename=Path(filename).name or "uploaded.bin",
                source_path=temp_path,
            )
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
                "storage_backend": settings.storage_backend,
                "storage_key": storage_key,
                "storage_url": storage_url,
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
