from app.rag.auto_retrieval import resolve_auto_retrieval


# Verifies test auto retrieval prefers sparse for short exact token queries so future changes cannot silently break this expected behavior.
def test_auto_retrieval_prefers_sparse_for_short_exact_token_queries():
    """Verify that auto retrieval prefers sparse for short exact token queries.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="What does ErrImagePull mean?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.auto_enabled is True
    assert decision.resolved_search_mode == "sparse"
    assert decision.enable_rerank is True
    assert decision.enable_crag is True
    assert "enable_rerank" in decision.auto_applied_flags
    assert "enable_crag" in decision.auto_applied_flags


# Verifies test auto retrieval prefers hybrid for policy questions so future changes cannot silently break this expected behavior.
def test_auto_retrieval_prefers_hybrid_for_policy_questions():
    """Verify that auto retrieval prefers hybrid for policy questions.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="What does our escalation policy say for P1 incidents?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.resolved_search_mode == "hybrid"
    assert decision.enable_rerank is True
    assert decision.enable_crag is True
    assert decision.enable_hyde is False


# Verifies test auto retrieval prefers dense hyde for semantic query so future changes cannot silently break this expected behavior.
def test_auto_retrieval_prefers_dense_hyde_for_semantic_query():
    """Verify that auto retrieval prefers dense hyde for semantic query.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="Can you summarize the overall intent behind the document and explain its main themes in simple terms?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.resolved_search_mode == "dense"
    assert decision.enable_hyde is True
    assert decision.enable_crag is False
    assert decision.enable_self_reflective is False


# Verifies test auto retrieval prefers hybrid without hyde for direct object comparison so future changes cannot silently break this expected behavior.
def test_auto_retrieval_prefers_hybrid_without_hyde_for_direct_object_comparison():
    """Verify that auto retrieval prefers hybrid without hyde for direct object comparison.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="What is the difference between a ConfigMap and a Secret in Kubernetes?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.resolved_search_mode == "hybrid"
    assert decision.enable_rerank is True
    assert decision.enable_hyde is False
    assert decision.enable_crag is False


# Verifies test auto retrieval prefers dense hyde crag srag for vague query so future changes cannot silently break this expected behavior.
def test_auto_retrieval_prefers_dense_hyde_crag_srag_for_vague_query():
    """Verify that auto retrieval prefers dense hyde crag srag for vague query.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="Why is this wrong?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.resolved_search_mode == "dense"
    assert decision.enable_hyde is True
    assert decision.enable_crag is True
    assert decision.enable_self_reflective is True


# Verifies test auto retrieval enables srag for ambiguous troubleshooting question so future changes cannot silently break this expected behavior.
def test_auto_retrieval_enables_srag_for_ambiguous_troubleshooting_question():
    """Verify that auto retrieval enables srag for ambiguous troubleshooting question.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    decision = resolve_auto_retrieval(
        question="My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?",
        search_mode="auto",
        enable_rerank=False,
        enable_hyde=False,
        enable_crag=False,
        enable_self_reflective=False,
    )

    assert decision.resolved_search_mode == "hybrid"
    assert decision.enable_rerank is True
    assert decision.enable_hyde is False
    assert decision.enable_crag is True
    assert decision.enable_self_reflective is True
    assert "enable_self_reflective" in decision.auto_applied_flags
