import shutil
import uuid
from pathlib import Path

from app.services.ingestion_service import IngestionService


def test_ingest_same_file_twice_skips_duplicate():
    service = IngestionService()

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
