from app.rag.hyde import HyDERetriever


def test_hyde_preserves_question_and_adds_domain_hypothesis(monkeypatch):
    """Verify that HyDE retains the query and generates Kubernetes evidence."""
    retriever = HyDERetriever(num_hypotheses=1)

    monkeypatch.setattr(
        "app.rag.hyde.generate",
        lambda **kwargs: {
            "text": (
                "Use a PersistentVolume and PersistentVolumeClaim so Kubernetes "
                "storage survives Pod replacement."
            )
        },
    )

    question = (
        "How can my application keep its data after it is restarted "
        "or moved to another machine?"
    )

    queries = retriever._generate_queries(question)

    assert queries[0] == question
    assert len(queries) == 2
    assert "PersistentVolume" in queries[1]
    assert "Kubernetes" in queries[1]
