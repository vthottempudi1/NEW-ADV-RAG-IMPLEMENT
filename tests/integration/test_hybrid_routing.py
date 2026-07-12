from app.core import graph as graph_module
from app.rag.hybrid_question import derive_hybrid_rag_question
from app.rag.router import classify_intent


def test_descriptive_which_questions_do_not_false_positive_as_sql():
    """Verify ordinary users and employee wording cannot trigger database execution."""
    assert classify_intent(
        "A container is alive, but users should not reach it until warm-up completes. Which Kubernetes mechanism controls that?"
    ) == "rag"
    assert classify_intent("Which employee approved yesterday's production change?") == "rag"


# Learner note: Verifies test classify intent returns hybrid for sql plus document question so future changes cannot silently break this expected behavior.
def test_classify_intent_returns_hybrid_for_sql_plus_document_question():
    """Verify that classify intent returns hybrid for sql plus document question.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    question = "How many users are there and what does the roadmap document say about AI roles?"
    assert classify_intent(question) == "hybrid"


# Learner note: Verifies mixed questions become focused document questions before retrieval features run.
def test_hybrid_question_decomposition_covers_operational_guidance_cases():
    """Verify that hybrid question decomposition covers operational guidance cases.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    cases = {
        "What is the average MTTR for prod-eu-west and how should we reduce it?": "incident response runbook",
        "How many open P2 alerts exist and what does our runbook say to do first?": "first response steps",
        "What cluster has unresolved incidents and what is the standard remediation procedure?": "standard remediation procedure",
        "How many P1 incidents breached SLA and what is our escalation policy?": "on-call escalation policy",
    }

    for question, expected in cases.items():
        assert expected in derive_hybrid_rag_question(question).lower()


def test_non_incident_policy_question_is_not_rewritten_as_on_call_escalation():
    """Domain policies such as NetworkPolicy must retain their original retrieval intent."""
    question = (
        "Only frontend Pods may call payments on TCP 8443, and payments must not initiate "
        "egress. What policy model expresses this?"
    )
    assert derive_hybrid_rag_question(question) == question


# Learner note: Verifies the hybrid graph sends only the focused RAG question into retrieval, HyDE, and CRAG.
def test_retrieve_rag_for_hybrid_uses_decomposed_question(monkeypatch):
    """Verify that retrieve rag for hybrid uses decomposed question.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    captured = {}

    # Learner Note: Fake run rag is part of the automated regression suite.
    def fake_run_rag(question, **kwargs):
        """Perform fake run rag for the automated regression suite.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        captured["question"] = question
        from app.models import ChatResponse, ResponseMetadata

        return ChatResponse(
            answer="Use the incident response runbook.",
            sources=["incident-response-runbook.html"],
            confidence=0.9,
            metadata=ResponseMetadata(route="rag"),
        )

    monkeypatch.setattr(graph_module, "run_rag", fake_run_rag)
    result = graph_module.retrieve_rag_for_hybrid(
        {
            "question": "What is the average MTTR for prod-eu-west and how should we reduce it?",
            "flags": {"search_mode": "hybrid", "enable_rerank": True, "enable_crag": True},
        }
    )

    assert "incident response runbook" in captured["question"].lower()
    assert result["rag_question"] == captured["question"]
    assert result["rag_metadata"]["retrieval_question"] == captured["question"]


# Learner note: Verifies test run hybrid combines rag and sql outputs so future changes cannot silently break this expected behavior.
def test_run_hybrid_combines_rag_and_sql_outputs(monkeypatch):
    """Verify that run hybrid combines rag and sql outputs.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    monkeypatch.setattr(
        graph_module.sql_service,
        "execute_sql",
        lambda sql: [{"total_users": 3}],
    )
    monkeypatch.setattr(
        graph_module,
        "generate",
        lambda system_prompt, user_message: {
            "text": "There are 3 users. The roadmap focuses on AI-for-chemistry roles.",
            "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        },
    )

    result = graph_module.run_hybrid(
        {
            "question": "How many users are there and what does the roadmap document say about AI roles?",
            "sql_approved": True,
            "generated_sql": "select count(*) as total_users from users",
            "rag_sources": ["roadmap.pdf"],
            "rag_metadata": {
                "retrieved_chunks": [
                    {
                        "text": "AI for chemistry roadmap with target roles and phases.",
                        "source": "roadmap.pdf",
                        "score": 0.91,
                        "retrieval_score": 0.91,
                        "rerank_score": None,
                    }
                ],
                "reflection_iterations": 1,
                "reflection_score": 0.8,
                "refined_question": "Summarize the roadmap and user count.",
            },
        }
    )

    assert result["final_answer"] == "There are 3 users. The roadmap focuses on AI-for-chemistry roles."
    assert result["metadata"]["route"] == "hybrid"
    assert result["metadata"]["reflection_iterations"] == 1
    assert result["metadata"]["reflection_score"] == 0.8
    assert result["metadata"]["sql_query"] == "select count(*) as total_users from users"
    assert result["metadata"]["sql_rows"] == [{"total_users": 3}]
    assert result["metadata"]["crag_score"] is None
    assert result["metadata"]["crag_label"] is None
    assert result["metadata"]["used_web_fallback"] is False
    assert "roadmap.pdf" in result["sources"]
    assert "database query" in result["sources"]
    sql_previews = [
        chunk
        for chunk in result["metadata"]["retrieved_chunks"]
        if chunk["source"] == "database query"
    ]
    assert len(sql_previews) == 1
    assert "SQL Results:" in sql_previews[0]["text"]
    assert result["cache_hit"] is False
    assert result["cost_saved_usd"] > 0


# Learner note: Verifies test run hybrid not approved preserves rag metadata so future changes cannot silently break this expected behavior.
def test_run_hybrid_not_approved_preserves_rag_metadata():
    """Verify that run hybrid not approved preserves rag metadata.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    result = graph_module.run_hybrid(
        {
            "question": "How many users are there and what does the roadmap document say about AI roles?",
            "sql_approved": False,
            "generated_sql": "select count(*) as total_users from users",
            "rag_sources": ["roadmap.pdf"],
            "rag_confidence": 0.77,
            "rag_metadata": {
                "retrieved_chunks": [
                    {
                        "text": "AI for chemistry roadmap with target roles and phases.",
                        "source": "roadmap.pdf",
                        "score": 0.91,
                        "retrieval_score": 0.91,
                        "rerank_score": None,
                    }
                ],
                "reflection_iterations": 1,
                "reflection_score": 0.8,
                "refined_question": "Summarize the roadmap and user count.",
                "crag_score": 0.6,
                "crag_label": "partially_relevant",
                "used_web_fallback": True,
            },
        }
    )

    assert result["final_answer"] == "SQL query was not approved."
    assert result["confidence"] == 0.77
    assert result["metadata"]["route"] == "hybrid"
    assert result["metadata"]["sql_query"] == "select count(*) as total_users from users"
    assert result["metadata"]["sql_rows"] == []
    assert result["metadata"]["crag_score"] == 0.6
    assert result["metadata"]["crag_label"] == "partially_relevant"
    assert result["metadata"]["used_web_fallback"] is True
