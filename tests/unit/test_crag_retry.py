from app.models import ChunkRelevance, CRAGEvaluation, RetrievedChunk
from app.rag import crag as crag_module


# Note: The grader contract must preserve independent scores for every evidence chunk.
def test_grade_chunks_parses_per_chunk_scores_and_aggregate_ratio(monkeypatch):
    """Verify that one strong chunk cannot raise an unrelated chunk's CRAG score."""
    chunks = [
        RetrievedChunk(text="generic scalable systems", source="noise.pdf", score=0.9),
        RetrievedChunk(text="Use kubectl scale deployment", source="scale-intro.html", score=0.8),
    ]
    monkeypatch.setattr(
        crag_module,
        "generate_with_json",
        lambda **kwargs: {
            "text": (
                '{"confidence": 0.98, "reasoning": "one relevant chunk", '
                '"chunk_evaluations": ['
                '{"index": 0, "relevance_score": 0.1, "relevance_label": "irrelevant", '
                '"reasoning": "generic topic only"}, '
                '{"index": 1, "relevance_score": 0.9, "relevance_label": "highly_relevant", '
                '"reasoning": "directly answers the question"}]}'
            )
        },
    )

    evaluation = crag_module.grade_chunks(
        "How do I scale a Kubernetes Deployment?",
        chunks,
    )

    assert [item.relevance_score for item in evaluation.chunk_evaluations] == [0.1, 0.9]
    assert evaluation.relevance_score == 0.5
    assert evaluation.relevant_chunk_count == 1
    assert evaluation.total_chunk_count == 2
    assert evaluation.relevant_ratio == 0.5
    assert evaluation.relevance_label == "somewhat_relevant"


# Note: Verifies CRAG retries locally even when initial retrieval is fully irrelevant.
def test_crag_retries_irrelevant_local_context_before_fallback(monkeypatch):
    """Verify that crag retries irrelevant local context before fallback.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    noisy = [RetrievedChunk(text="unrelated research", source="noise.pdf", score=0.9)]
    runbook = [
        RetrievedChunk(
            text="First response steps include severity and impact triage.",
            source="incident-response-runbook.html",
            score=0.8,
        )
    ]
    evaluations = iter(
        [
            CRAGEvaluation(
                relevance_score=0.1,
                relevance_label="irrelevant",
                confidence=1.0,
                chunk_evaluations=[
                    ChunkRelevance(index=0, source="noise.pdf", relevance_score=0.1)
                ],
                total_chunk_count=1,
                relevant_ratio=0.0,
            ),
            CRAGEvaluation(
                relevance_score=0.95,
                relevance_label="highly_relevant",
                confidence=1.0,
                chunk_evaluations=[
                    ChunkRelevance(
                        index=0,
                        source="incident-response-runbook.html",
                        relevance_score=0.95,
                    )
                ],
                relevant_chunk_count=1,
                total_chunk_count=1,
                relevant_ratio=1.0,
            ),
        ]
    )
    monkeypatch.setattr(crag_module, "grade_chunks", lambda question, chunks: next(evaluations))

    chunks, evaluation, used_web = crag_module.crag_pipeline(
        question="What are the first response steps in our incident response runbook?",
        chunks=noisy,
        enable_crag=True,
        local_retry_fn=lambda: runbook,
        allow_web_fallback=False,
    )

    assert chunks == runbook
    assert evaluation.relevance_score == 0.95
    assert used_web is False


# Note: Per-chunk CRAG must remove noisy evidence even when one chunk is excellent.
def test_crag_filters_individually_irrelevant_chunks(monkeypatch):
    """Verify that aggregate relevance cannot hide an irrelevant first-ranked chunk."""
    chunks = [
        RetrievedChunk(text="scalable web thesis", source="noise.pdf", score=0.9),
        RetrievedChunk(text="kubectl scale deployment", source="scale-intro.html", score=0.8),
    ]
    evaluation = CRAGEvaluation(
        relevance_score=0.5,
        relevance_label="somewhat_relevant",
        confidence=1.0,
        chunk_evaluations=[
            ChunkRelevance(index=0, source="noise.pdf", relevance_score=0.1),
            ChunkRelevance(index=1, source="scale-intro.html", relevance_score=0.9),
        ],
        relevant_chunk_count=1,
        total_chunk_count=2,
        relevant_ratio=0.5,
    )
    monkeypatch.setattr(crag_module, "grade_chunks", lambda question, values: evaluation)

    filtered, result, used_web = crag_module.crag_pipeline(
        question="How do I scale a Kubernetes Deployment?",
        chunks=chunks,
        enable_crag=True,
        local_retry_fn=None,
        allow_web_fallback=False,
    )

    assert [chunk.source for chunk in filtered] == ["scale-intro.html"]
    assert result.relevant_ratio == 0.5
    assert used_web is False


def test_crag_prompt_includes_authority_tier(monkeypatch):
    """Verify that CRAG receives authority metadata and evaluation guidance."""
    captured = {}

    def fake_generate_with_json(**kwargs):
        """Capture the generated prompt and return a deterministic evaluation."""
        captured.update(kwargs)
        return {
            "text": (
                '{"confidence": 0.9, '
                '"reasoning": "authority-aware evaluation", '
                '"chunk_evaluations": ['
                '{"index": 0, "relevance_score": 0.9, '
                '"relevance_label": "highly_relevant", '
                '"reasoning": "authoritative evidence"},'
                '{"index": 1, "relevance_score": 0.1, '
                '"relevance_label": "irrelevant", '
                '"reasoning": "noisy research"}'
                "]}"
            )
        }

    monkeypatch.setattr(
        crag_module,
        "generate_with_json",
        fake_generate_with_json,
    )

    chunks = [
        RetrievedChunk(
            text="A Kubernetes Service provides a stable endpoint.",
            source="concepts__services-networking__service.txt",
            metadata={"authority_tier": "true"},
        ),
        RetrievedChunk(
            text="General research about scalable web servers.",
            source="scalable-web-thesis.pdf",
            metadata={"authority_tier": "noisy"},
        ),
    ]

    crag_module.grade_chunks(
        "How can applications find each other when addresses change?",
        chunks,
    )

    prompt = captured["user_message"]
    system_prompt = captured["system_prompt"]

    assert "[Authority tier: true]" in prompt
    assert "[Authority tier: noisy]" in prompt

    assert "Topical similarity alone is insufficient" in system_prompt
    assert "authority_tier=noisy" in system_prompt
    assert "authority_tier=true" in system_prompt
    assert "authority_tier=uploaded" in system_prompt
