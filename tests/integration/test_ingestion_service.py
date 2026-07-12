import shutil
import uuid
from pathlib import Path

from app.ingestion import service as ingestion_module
from app.ingestion.document_processor import DocumentProcessor
from app.ingestion.service import IngestionService
from app.models import RetrievedChunk


def test_long_text_chunks_end_and_restart_on_sentence_boundaries():
    """Evidence chunks must preserve complete sentences around overlap boundaries."""
    sentences = [f"Sentence {index} contains reliable Kubernetes evidence." for index in range(80)]
    text = " ".join(sentences)

    chunks = DocumentProcessor()._chunk_text(
        text=text,
        source_name="evidence.txt",
        source_path="evidence.txt",
        page_number=None,
    )

    assert len(chunks) > 1
    assert all(chunk["text"].endswith(".") for chunk in chunks)
    assert all(chunk["text"].startswith("Sentence ") for chunk in chunks)
    assert all(len(chunk["text"]) <= 1000 for chunk in chunks)


def test_large_document_embeddings_are_processed_in_bounded_batches(monkeypatch):
    """Large documents must never build one unbounded embedding/upsert request."""
    embedded_batch_sizes = []
    upserted_batch_sizes = []
    monkeypatch.setattr(
        ingestion_module,
        "embed_texts",
        lambda texts, **kwargs: embedded_batch_sizes.append(len(texts)) or [[0.1] for _ in texts],
    )
    monkeypatch.setattr(
        ingestion_module,
        "upsert_chunks",
        lambda chunks, embeddings: upserted_batch_sizes.append(len(chunks)),
    )
    chunks = [RetrievedChunk(text=f"chunk {index}", source="large.pdf") for index in range(130)]

    IngestionService.__new__(IngestionService)._embed_and_upsert_chunks(chunks)

    assert embedded_batch_sizes == [64, 64, 2]
    assert upserted_batch_sizes == [64, 64, 2]


# Learner note: Verifies test ingest same file twice skips duplicate so future changes cannot silently break this expected behavior.
def test_ingest_same_file_twice_skips_duplicate(monkeypatch):
    """Verify that ingest same file twice skips duplicate.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    service = IngestionService()
    stored: dict[str, bytes] = {}

    # Learner Note: Fake storage is part of the automated regression suite.
    class _FakeStorage:
        # Learner note: Supports exists as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake storage within the automated regression suite.

        Learner Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        def exists(self, key: str) -> bool:
            """Perform exists for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return key in stored

        # Learner note: Supports save bytes as reusable test setup so scenarios stay deterministic and readable.
        def save_bytes(self, key: str, data: bytes) -> None:
            """Perform save bytes for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            stored[key] = data

        # Learner note: Supports read bytes as reusable test setup so scenarios stay deterministic and readable.
        def read_bytes(self, key: str) -> bytes:
            """Perform read bytes for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return stored[key]

        # Learner note: Supports url for as reusable test setup so scenarios stay deterministic and readable.
        def url_for(self, key: str) -> str:
            """Perform url for for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return f"memory://{key}"

    service.storage = _FakeStorage()
    service.doc_cache.backend = service.storage

    monkeypatch.setattr(
        ingestion_module,
        "embed_texts",
        lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts],
    )
    indexed_chunks = []
    monkeypatch.setattr(
        ingestion_module,
        "upsert_chunks",
        lambda chunks, embeddings: indexed_chunks.extend(chunks),
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
        assert indexed_chunks
        metadata = indexed_chunks[0].metadata
        assert metadata["document_id"] == first["content_hash"]
        assert metadata["content_hash"] == first["content_hash"]
        assert metadata["authority_tier"] == "uploaded"
        assert metadata["chunk_index"] == 0
        assert metadata["total_chunks"] == len(indexed_chunks)
        assert metadata["ingestion_version"] == "v2"
        assert second["status"] == "skipped"
        assert second["reason"] == "already_indexed"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
