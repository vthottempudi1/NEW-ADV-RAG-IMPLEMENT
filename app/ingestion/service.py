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


class IngestionService:
    """Coordinates the end-to-end document ingestion pipeline.

    Handles content-hash based deduplication, persisting raw document bytes
    to the configured storage backend, running documents through the chunker,
    embedding and upserting chunks into Qdrant, and recording per-document
    metadata in the document cache so repeat ingestion of the same content
    can be skipped.
    """

    def __init__(self):
        """Wire up the document cache, document processor, and storage backend."""
        self.doc_cache = DocCacheService()
        self.processor = DocumentProcessor()
        self.storage = get_storage_backend()

    def _storage_key(self, content_hash: str, filename: str) -> str:
        """Build the storage path for a document from its content hash and filename.

        Falls back to "uploaded.bin" if `filename` has no usable name component.
        """
        safe_name = Path(filename).name or "uploaded.bin"
        return f"documents/{content_hash}/{safe_name}"

    def _normalize_chunk_sources(
        self,
        chunks_meta: list[dict],
        *,
        filename: str,
        source_path: str,
    ) -> list[dict]:
        """Return copies of `chunks_meta` with source fields overwritten to `filename`/`source_path`.

        Ensures every chunk produced for a document reports the same
        `source`, `source_name`, and `source_path`, regardless of what the
        underlying document processor populated.
        """
        normalized: list[dict] = []
        for item in chunks_meta:
            updated = dict(item)
            updated["source"] = filename
            updated["source_name"] = filename
            updated["source_path"] = source_path
            normalized.append(updated)
        return normalized

    def ingest_file(
        self,
        file_path: str,
        *,
        force_reindex: bool = False,
        authority_tier: str = "uploaded",
        ingestion_version: str = "v2",
    ) -> dict:
        """Ingest a document from a local file path into the RAG pipeline.

        Reads the file's bytes, computes a content hash, and always persists
        a copy to the configured storage backend under a hash-based key. If
        the document was already indexed under the same `ingestion_version`
        and `force_reindex` is False, returns early with status "skipped"
        and the previously cached metadata instead of reprocessing.

        Otherwise, chunks the document, normalizes each chunk's source
        fields to the original filename, builds `RetrievedChunk` models
        tagged with `content_hash`/`authority_tier`, embeds and upserts them
        into Qdrant in batches, and records the resulting metadata (chunk
        count, page count, storage location, etc.) in the document cache.

        Returns a dict with "status" ("indexed" or "skipped"),
        "content_hash", "chunks_indexed", and "metadata" (plus "reason" and
        storage details when skipped).
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

    def ingest_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        force_reindex: bool = False,
    ) -> dict:
        """Ingest a document supplied as raw bytes (e.g., an uploaded file).

        Computes the content hash directly from `content`; if not
        `force_reindex` and a document with that hash is already indexed at
        ingestion version "v2", returns early with status "skipped" and the
        cached metadata. Otherwise persists the bytes to the storage
        backend, writes them to a temporary file (the document processor
        requires a file path), runs the same chunk/embed/upsert flow as
        `ingest_file` with `authority_tier="uploaded"` and
        `ingestion_version="v2"`, and always removes the temporary file in a
        `finally` block regardless of success or failure.

        Returns a dict with "status" ("indexed" or "skipped"),
        "content_hash", "chunks_indexed", and "metadata".
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

    def _already_indexed(self, content_hash: str, ingestion_version: str) -> bool:
        """Return True if `content_hash` has cached metadata matching the current collection and version.

        Used to decide whether ingestion can be skipped: requires cached
        metadata to exist, its `collection_name` to match the currently
        configured Qdrant collection, and its `ingestion_version` to match
        the requested one.
        """
        metadata = self.doc_cache.get_metadata(content_hash)
        if not metadata:
            return False
        return (
            metadata.get("collection_name") == settings.qdrant_collection
            and metadata.get("ingestion_version") == ingestion_version
        )

    def _embed_and_upsert_chunks(self, chunks: list[RetrievedChunk]) -> None:
        """Embed and upsert `chunks` into the vector store in fixed-size batches.

        Batches of `_INGESTION_BATCH_SIZE` chunks are embedded (bypassing
        the embedding cache) and upserted one batch at a time, with the
        embeddings list explicitly deleted and garbage collection forced
        after each batch, so ingesting large documents does not exhaust
        memory.
        """
        for start in range(0, len(chunks), _INGESTION_BATCH_SIZE):
            batch = chunks[start:start + _INGESTION_BATCH_SIZE]
            embeddings = embed_texts(
                [chunk.text for chunk in batch],
                use_cache=False,
            )
            upsert_chunks(batch, embeddings)
            del embeddings
            gc.collect()

    def _build_chunk_models(
        self,
        chunks_meta: list[dict],
        *,
        content_hash: str,
        authority_tier: str,
        ingestion_version: str,
    ) -> list[RetrievedChunk]:
        """Convert raw chunk metadata dicts into `RetrievedChunk` models.

        Drops any chunk with empty/missing text, then builds a
        `RetrievedChunk` for each remaining item with a `metadata` dict
        carrying `document_id`/`content_hash`, `authority_tier`, a 0-based
        `chunk_index`, the `total_chunks` count, `page_number`,
        `source_path`, and `ingestion_version`.
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

    def _page_count(self, chunks_meta: list[dict]) -> int:
        """Return the number of distinct page numbers present across `chunks_meta`.

        Chunks with no recorded `page_number` are ignored.
        """
        pages = {
            item.get("page_number")
            for item in chunks_meta
            if item.get("page_number") is not None
        }
        return len(pages)
