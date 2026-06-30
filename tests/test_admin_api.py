from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import create_access_token
from app.services.query_cache_service import query_cache


client = TestClient(app)


def _admin_token() -> str:
    return create_access_token("testuser@example.com", is_admin=True)


def test_admin_can_clear_targeted_rag_cache_entry():
    original_redis = query_cache._redis_client
    query_cache._redis_client = None
    query_cache.clear()

    question = "What does error ErrImagePull mean and how do I fix it?"
    context = {
        "schema_version": 8,
        "top_k": 5,
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": False,
        "enable_self_reflective": False,
    }
    payload = {"answer": "stale", "sources": ["old.pdf"], "confidence": 0.7}
    query_cache.set_rag_answer(question, payload, context)

    try:
        assert query_cache.get_rag_answer(question, context) == payload

        response = client.post(
            "/admin/cache/clear",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "tier": "rag_answer",
                "question": question,
                "cache_context": context,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["scope"] == "targeted"
        assert body["cleared"]["tier"] == "rag_answer"
        assert body["cleared"]["memory_deleted"] is True
        assert query_cache.get_rag_answer(question, context) is None
    finally:
        query_cache.clear()
        query_cache._redis_client = original_redis
