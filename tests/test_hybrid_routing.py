from app.core import graph as graph_module
from app.services.router_service import classify_intent


def test_classify_intent_returns_hybrid_for_sql_plus_document_question():
    question = "How many users are there and what does the roadmap document say about AI roles?"
    assert classify_intent(question) == "hybrid"


def test_run_hybrid_combines_rag_and_sql_outputs(monkeypatch):
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
    assert result["cache_hit"] is False
    assert result["cost_saved_usd"] > 0


def test_run_hybrid_not_approved_preserves_rag_metadata():
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
