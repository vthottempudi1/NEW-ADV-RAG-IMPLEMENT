"""Streamlit component tests for critical answer and metadata states."""

from streamlit.testing.v1 import AppTest

from ui.streamlit.app import USE_CASES


# Learner Note: Load the UI component inside Streamlit's isolated script context.
def _render_payload(payload):
    """Import and render the answer component inside an AppTest execution context."""
    from ui.streamlit.app import _render_answer_card

    _render_answer_card(payload)


# Learner Note: Render dependency health in isolation to protect the sidebar status contract.
def _render_dependency_health(payload):
    """Import and render the dependency health component inside an AppTest context."""
    from ui.streamlit.app import _render_health_card

    _render_health_card(payload)


# Learner Note: Every presentation preset must map to a supported backend request shape.
def test_frontend_presets_have_complete_retrieval_configuration():
    """Verify that all hiring-demo presets define every required query control."""
    required = {
        "question",
        "search_mode",
        "enable_rerank",
        "enable_hyde",
        "enable_crag",
        "enable_self_reflective",
        "top_k",
        "label",
    }

    assert len(USE_CASES) >= 6
    for preset in USE_CASES.values():
        assert required <= preset.keys()
        assert preset["question"].strip()


# Learner Note: The Ping Backend result must show each infrastructure dependency under the button.
def test_frontend_renders_dependency_connectivity():
    """Verify PostgreSQL, Qdrant, Redis, and S3 connectivity badges render together."""
    payload = {
        "status": "degraded",
        "active_collection": "new_adv_rag_documents_v2",
        "dependencies": {
            "postgres": {"status": "connected", "latency_ms": 12.0},
            "qdrant": {"status": "connected", "latency_ms": 24.0},
            "redis": {"status": "unavailable", "latency_ms": 40.0},
            "s3": {"status": "connected", "latency_ms": 18.0},
        },
    }

    app = AppTest.from_function(_render_dependency_health, args=(payload,)).run()

    assert not app.exception
    rendered = " ".join(item.value for item in app.markdown)
    assert "postgres: connected" in rendered
    assert "qdrant: connected" in rendered
    assert "redis: unavailable" in rendered
    assert "s3: connected" in rendered


# Learner Note: Clarification must render as a successful no-source UI state.
def test_frontend_renders_clarification_without_fake_chunks():
    """Verify that the UI presents a clarification prompt without retrieval evidence."""
    payload = {
        "answer": "What do you want to scale—a Deployment, StatefulSet, or cluster?",
        "sources": [],
        "confidence": 1.0,
        "cache_hit": False,
        "cost_saved": "$0.00",
        "llm_cost_saved": "$0.00",
        "infra_cost_saved": "$0.00",
        "metadata": {
            "route": "clarification",
            "retrieved_chunks": [],
            "needs_clarification": True,
            "clarification_type": "scaling",
            "clarification_question": "What do you want to scale?",
        },
    }

    app = AppTest.from_function(_render_payload, args=(payload,)).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Answer",
        "Sources",
        "Chunks",
        "Metadata",
        "Raw JSON",
    ]
    assert any("CLARIFICATION" in item.value for item in app.markdown)
    assert any("No sources returned" in item.value for item in app.info)
    assert any("No retrieved chunk previews" in item.value for item in app.info)


# Learner Note: CRAG evidence-level diagnostics must remain visible in the frontend.
def test_frontend_renders_chunk_scores_and_crag_ratio():
    """Verify that source, chunk, and per-chunk CRAG metadata render without errors."""
    payload = {
        "answer": "Scale the Deployment with kubectl scale.",
        "sources": ["tutorials__kubernetes-basics__scale__scale-intro.html"],
        "confidence": 0.9,
        "cache_hit": False,
        "cost_saved": "$0.00",
        "llm_cost_saved": "$0.00",
        "infra_cost_saved": "$0.00",
        "metadata": {
            "route": "rag",
            "retrieved_chunks": [
                {
                    "text": "Use kubectl scale deployment.",
                    "source": "tutorials__kubernetes-basics__scale__scale-intro.html",
                    "score": 0.92,
                    "retrieval_score": 0.88,
                    "rerank_score": 6.4,
                }
            ],
            "crag_score": 0.95,
            "crag_label": "highly_relevant",
            "crag_relevant_chunks": 1,
            "crag_total_chunks": 1,
            "crag_relevant_ratio": 1.0,
            "crag_chunk_scores": [
                {
                    "index": 0,
                    "source": "tutorials__kubernetes-basics__scale__scale-intro.html",
                    "relevance_score": 0.95,
                    "relevance_label": "highly_relevant",
                }
            ],
        },
    }

    app = AppTest.from_function(_render_payload, args=(payload,)).run()

    assert not app.exception
    assert any("CRAG Relevant Ratio" in item.value for item in app.markdown)
    assert any("rerank=6.4" in item.value for item in app.caption)
