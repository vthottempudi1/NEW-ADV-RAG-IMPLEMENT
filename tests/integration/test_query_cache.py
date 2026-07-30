from app.caching.query_cache import QueryCacheService


# Note: Verifies test rag cache round trip so future changes cannot silently break this expected behavior.
def test_rag_cache_round_trip():
    """Verify that rag cache round trip.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    cache = QueryCacheService()
    context = {"schema_version": 1, "top_k": 5, "search_mode": "dense"}

    assert cache.get_rag_answer("what is this", context) is None

    payload = {"answer": "hello", "sources": ["doc1"], "confidence": 0.7}
    cache.set_rag_answer("what is this", payload, context)

    cached = cache.get_rag_answer("what is this", context)
    assert cached is not None
    assert cached["answer"] == "hello"


# Note: Verifies test rag cache separates search mode so future changes cannot silently break this expected behavior.
def test_rag_cache_separates_search_mode():
    """Verify that rag cache separates search mode.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    cache = QueryCacheService()
    dense_context = {"schema_version": 1, "top_k": 5, "search_mode": "dense"}
    hybrid_context = {"schema_version": 1, "top_k": 5, "search_mode": "hybrid"}

    payload = {"answer": "dense answer", "sources": ["doc1"], "confidence": 0.7}
    cache.set_rag_answer("same question", payload, dense_context)

    assert cache.get_rag_answer("same question", dense_context) is not None
    assert cache.get_rag_answer("same question", hybrid_context) is None
