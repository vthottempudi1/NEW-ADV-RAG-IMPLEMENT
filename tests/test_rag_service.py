from app.models import RetrievedChunk
from app.services.rag_service import _calculate_confidence


def test_calculate_confidence_returns_zero_without_chunks():
    confidence = _calculate_confidence(
        chunks=[],
        top_k=5,
        enable_crag=False,
        crag_score=None,
        reflection_score=None,
    )

    assert confidence == 0.0


def test_calculate_confidence_increases_with_stronger_signals():
    weak_chunks = [
        RetrievedChunk(text="weak", source="doc1", score=0.08, retrieval_score=0.08),
        RetrievedChunk(text="weak-2", source="doc2", score=0.05, retrieval_score=0.05),
    ]
    strong_chunks = [
        RetrievedChunk(text="strong", source="doc1", score=0.92, retrieval_score=0.92),
        RetrievedChunk(text="strong-2", source="doc2", score=0.83, retrieval_score=0.83),
        RetrievedChunk(text="strong-3", source="doc3", score=0.78, retrieval_score=0.78),
        RetrievedChunk(text="strong-4", source="doc4", score=0.71, retrieval_score=0.71),
        RetrievedChunk(text="strong-5", source="doc5", score=0.69, retrieval_score=0.69),
    ]

    weak_confidence = _calculate_confidence(
        chunks=weak_chunks,
        top_k=5,
        enable_crag=False,
        crag_score=None,
        reflection_score=None,
    )
    strong_confidence = _calculate_confidence(
        chunks=strong_chunks,
        top_k=5,
        enable_crag=True,
        crag_score=1.0,
        reflection_score=5.0,
    )

    assert 0.0 < weak_confidence < strong_confidence <= 1.0
