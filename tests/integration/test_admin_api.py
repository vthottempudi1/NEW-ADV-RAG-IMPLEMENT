import importlib

from fastapi.testclient import TestClient

from app.caching.query_cache import query_cache
from app.main import app
from app.middleware.auth import create_access_token

client = TestClient(app)
admin_api = importlib.import_module("app.api.v1.admin")


# Learner Note: Admin dependency health returns one safe status contract for all four data services.
def test_admin_dependency_health_reports_all_connected(monkeypatch):
    """Verify concurrent dependency probes return status and latency without sensitive details."""
    for name in ("postgres", "qdrant", "redis", "s3"):
        monkeypatch.setattr(admin_api, f"_probe_{name}", lambda: None)

    response = client.get(
        "/admin/health",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["dependencies"]) == {"postgres", "qdrant", "redis", "s3"}
    assert all(item["status"] == "connected" for item in body["dependencies"].values())
    assert all("latency_ms" in item for item in body["dependencies"].values())
    assert "error" not in str(body).lower()


# Learner Note: Optional cache failure degrades visibility without declaring core retrieval dead.
def test_admin_dependency_health_marks_redis_failure_degraded(monkeypatch):
    """Verify Redis failure is degraded while healthy PostgreSQL and Qdrant remain usable."""
    monkeypatch.setattr(admin_api, "_probe_postgres", lambda: None)
    monkeypatch.setattr(admin_api, "_probe_qdrant", lambda: None)
    monkeypatch.setattr(admin_api, "_probe_s3", lambda: None)

    def fail_redis() -> None:
        """Simulate an unavailable optional distributed cache."""
        raise RuntimeError("test failure")

    monkeypatch.setattr(admin_api, "_probe_redis", fail_redis)

    response = client.get(
        "/admin/health",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"]["status"] == "unavailable"


# Learner note: Supports admin token as reusable test setup so scenarios stay deterministic and readable.
def _admin_token() -> str:
    """Support the automated regression suite by performing admin token.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return create_access_token("testuser@example.com", is_admin=True)


# Learner note: Verifies test admin can clear targeted rag cache entry so future changes cannot silently break this expected behavior.
def test_admin_can_clear_targeted_rag_cache_entry():
    """Verify that admin can clear targeted rag cache entry.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
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
