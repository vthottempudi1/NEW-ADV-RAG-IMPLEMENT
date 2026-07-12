from __future__ import annotations

import gc
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.caching.document_cache import DocCacheService

#from docx import settings
from app.config import settings
from app.ingestion.document_processor import DocumentProcessor
from app.models import RetrievedChunk
from app.rag.embedding_service import embed_texts
from app.rag.vector_store import upsert_chunks
from app.storage.storage_backend import get_storage_backend

_INGESTION_BATCH_SIZE = 64


# Learner Note: Ingestion service is part of the document ingestion pipeline.
class IngestionService:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent ingestion service within the document ingestion pipeline.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.doc_cache = DocCacheService()
        self.processor = DocumentProcessor()
        self.storage = get_storage_backend()

    # Learner note: Encapsulates storage key so this responsibility can be understood, tested, and changed independently.
    def _storage_key(self, content_hash: str, filename: str) -> str:
        """Support the document ingestion pipeline by performing storage key.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        safe_name = Path(filename).name or "uploaded.bin"
        return f"documents/{content_hash}/{safe_name}"

    # Learner note: Encapsulates normalize chunk sources so this responsibility can be understood, tested, and changed independently.
    def _normalize_chunk_sources(
        self,
        chunks_meta: list[dict],
        *,
        filename: str,
        source_path: str,
    ) -> list[dict]:
        """Support the document ingestion pipeline by performing normalize chunk sources.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        normalized: list[dict] = []
        for item in chunks_meta:
            updated = dict(item)
            updated["source"] = filename
            updated["source_name"] = filename
            updated["source_path"] = source_path
            normalized.append(updated)
        return normalized

    # Learner note: Handles ingest file as an isolated ingestion step so failures are easier to diagnose.
    def ingest_file(
        self,
        file_path: str,
        *,
        force_reindex: bool = False,
        authority_tier: str = "uploaded",
        ingestion_version: str = "v2",
    ) -> dict:
        """Perform ingest file for the document ingestion pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        path = Path(file_path)
        content_hash = self.doc_cache.compute_file_hash(path)
        content = path.read_bytes()
        storage_key = self._storage_key(content_hash, path.name)
        self.storage.save_bytes(storage_key, content)
        storage_url = self.storage.url_for(storage_key)

        if not force_reindex and self._already_indexed(content_hash, ingestion_version):
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
        chunks = self._build_chunk_models(
            chunks_meta,
            content_hash=content_hash,
            authority_tier=authority_tier,
            ingestion_version=ingestion_version,
        )
        self._embed_and_upsert_chunks(chunks)

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
            "authority_tier": authority_tier,
            "ingestion_version": ingestion_version,
        }
        self.doc_cache.set_metadata(content_hash, metadata)

        return {
            "status": "indexed",
            "content_hash": content_hash,
            "chunks_indexed": len(chunks),
            "metadata": metadata,
        }

    # Learner note: Handles ingest bytes as an isolated ingestion step so failures are easier to diagnose.
    def ingest_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        force_reindex: bool = False,
    ) -> dict:
        """Perform ingest bytes for the document ingestion pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        content_hash = self.doc_cache.compute_content_hash(content)

        if not force_reindex and self._already_indexed(content_hash, "v2"):
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
            chunks = self._build_chunk_models(
                chunks_meta,
                content_hash=content_hash,
                authority_tier="uploaded",
                ingestion_version="v2",
            )
            self._embed_and_upsert_chunks(chunks)

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
                "authority_tier": "uploaded",
                "ingestion_version": "v2",
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

    # Learner note: Encapsulates already indexed so this responsibility can be understood, tested, and changed independently.
    def _already_indexed(self, content_hash: str, ingestion_version: str) -> bool:
        """Support the document ingestion pipeline by performing already indexed.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        metadata = self.doc_cache.get_metadata(content_hash)
        if not metadata:
            return False
        return (
            metadata.get("collection_name") == settings.qdrant_collection
            and metadata.get("ingestion_version") == ingestion_version
        )

    def _embed_and_upsert_chunks(self, chunks: list[RetrievedChunk]) -> None:
        """Embed and persist bounded batches so large documents cannot exhaust memory."""
        for start in range(0, len(chunks), _INGESTION_BATCH_SIZE):
            batch = chunks[start:start + _INGESTION_BATCH_SIZE]
            embeddings = embed_texts(
                [chunk.text for chunk in batch],
                use_cache=False,
            )
            upsert_chunks(batch, embeddings)
            del embeddings
            gc.collect()

    # Learner note: Encapsulates build chunk models so this responsibility can be understood, tested, and changed independently.
    def _build_chunk_models(
        self,
        chunks_meta: list[dict],
        *,
        content_hash: str,
        authority_tier: str,
        ingestion_version: str,
    ) -> list[RetrievedChunk]:
        """Support the document ingestion pipeline by performing build chunk models.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        populated = [item for item in chunks_meta if item.get("text")]
        total_chunks = len(populated)
        return [
            RetrievedChunk(
                text=item["text"],
                source=item.get("source_name") or item.get("source", "unknown"),
                metadata={
                    "document_id": content_hash,
                    "content_hash": content_hash,
                    "authority_tier": authority_tier,
                    "chunk_index": chunk_index,
                    "total_chunks": total_chunks,
                    "page_number": item.get("page_number"),
                    "source_path": item.get("source_path", ""),
                    "ingestion_version": ingestion_version,
                },
            )
            for chunk_index, item in enumerate(populated)
        ]

    # Learner note: Encapsulates page count so this responsibility can be understood, tested, and changed independently.
    def _page_count(self, chunks_meta: list[dict]) -> int:
        """Support the document ingestion pipeline by performing page count.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        pages = {
            item.get("page_number")
            for item in chunks_meta
            if item.get("page_number") is not None
        }
        return len(pages)
