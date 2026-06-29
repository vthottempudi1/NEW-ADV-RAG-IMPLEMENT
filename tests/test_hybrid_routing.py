from app.core import graph as graph_module
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.services.router_service import classify_intent


def test_classify_intent_returns_hybrid_for_sql_plus_document_question():
    question = "How many users are there and what does the roadmap document say about AI roles?"
    assert classify_intent(question) == "hybrid"


def test_run_hybrid_combines_rag_and_sql_outputs(monkeypatch):
    def fake_run_rag(*args, **kwargs):
        return ChatResponse(
            answer="The roadmap focuses on AI-for-chemistry roles.",
            sources=["roadmap.pdf"],
            confidence=0.72,
            metadata=ResponseMetadata(
                route="rag",
                retrieved_chunks=[
                    RetrievedChunkPreview(
                        text="AI for chemistry roadmap with target roles and phases.",
                        source="roadmap.pdf",
                        score=0.91,
                        retrieval_score=0.91,
                    )
                ],
                reflection_iterations=1,
                reflection_score=0.8,
                refined_question="Summarize the roadmap and user count.",
            ),
        )

    monkeypatch.setattr(graph_module, "run_rag", fake_run_rag)
    monkeypatch.setattr(
        graph_module.sql_service,
        "generate_sql",
        lambda question: {"sql": "select count(*) as total_users from users"},
    )
    monkeypatch.setattr(
        graph_module.sql_service,
        "execute_sql",
        lambda sql: [{"total_users": 3}],
    )
    monkeypatch.setattr(
        graph_module,
        "generate",
        lambda system_prompt, user_message: {
            "text": "There are 3 users. The roadmap focuses on AI-for-chemistry roles."
        },
    )

    result = graph_module.run_hybrid(
        {
            "question": "How many users are there and what does the roadmap document say about AI roles?",
            "flags": {
                "top_k": 5,
                "search_mode": "hybrid",
                "enable_rerank": True,
                "enable_hyde": False,
                "enable_crag": False,
                "enable_self_reflective": True,
            },
        }
    )

    assert result["final_answer"] == "There are 3 users. The roadmap focuses on AI-for-chemistry roles."
    assert result["metadata"]["route"] == "hybrid"
    assert result["metadata"]["reflection_iterations"] == 1
    assert result["metadata"]["reflection_score"] == 0.8
    assert "roadmap.pdf" in result["sources"]
    assert "database query" in result["sources"]
    assert result["cache_hit"] is False
