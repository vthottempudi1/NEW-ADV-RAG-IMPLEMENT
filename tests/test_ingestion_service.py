import shutil
import uuid
from pathlib import Path

from app.services import ingestion_service as ingestion_module
from app.services.ingestion_service import IngestionService


def test_ingest_same_file_twice_skips_duplicate(monkeypatch):
    service = IngestionService()
    stored: dict[str, bytes] = {}

    class _FakeStorage:
        def exists(self, key: str) -> bool:
            return key in stored

        def save_bytes(self, key: str, data: bytes) -> None:
            stored[key] = data

        def read_bytes(self, key: str) -> bytes:
            return stored[key]

        def url_for(self, key: str) -> str:
            return f"memory://{key}"

    service.storage = _FakeStorage()
    service.doc_cache.backend = service.storage

    monkeypatch.setattr(
        ingestion_module,
        "embed_texts",
        lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
    )
    monkeypatch.setattr(
        ingestion_module,
        "upsert_chunks",
        lambda chunks, embeddings: None,
    )

    temp_dir = Path(".cache") / "test_ingestion" / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_path = temp_dir / "sample.txt"

    try:
        file_path.write_text(
            "AI for chemistry career roadmap. Learn Python, ML, deep learning, and scientific AI.",
            encoding="utf-8",
        )

        first = service.ingest_file(str(file_path))
        second = service.ingest_file(str(file_path))

        assert first["status"] in {"indexed", "skipped"}
        assert second["status"] == "skipped"
        assert second["reason"] == "already_indexed"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
