from app.services.query_cache_service import QueryCacheService


def test_rag_cache_round_trip():
    cache = QueryCacheService()
    context = {"schema_version": 1, "top_k": 5, "search_mode": "dense"}

    assert cache.get_rag_answer("what is this", context) is None

    payload = {"answer": "hello", "sources": ["doc1"], "confidence": 0.7}
    cache.set_rag_answer("what is this", payload, context)

    cached = cache.get_rag_answer("what is this", context)
    assert cached is not None
    assert cached["answer"] == "hello"


def test_rag_cache_separates_search_mode():
    cache = QueryCacheService()
    dense_context = {"schema_version": 1, "top_k": 5, "search_mode": "dense"}
    hybrid_context = {"schema_version": 1, "top_k": 5, "search_mode": "hybrid"}

    payload = {"answer": "dense answer", "sources": ["doc1"], "confidence": 0.7}
    cache.set_rag_answer("same question", payload, dense_context)

    assert cache.get_rag_answer("same question", dense_context) is not None
    assert cache.get_rag_answer("same question", hybrid_context) is None