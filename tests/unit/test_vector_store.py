from app.models import RetrievedChunk
from app.rag import vector_store


# Note: Test upsert persists chunk audit metadata is part of the automated regression suite.
def test_upsert_persists_chunk_audit_metadata(monkeypatch):
    """Qdrant payloads must retain v2 document and chunk provenance."""
    captured = {}

    # Client is part of the automated regression suite.
    class _Client:
        """Capture Qdrant upsert arguments without making a network request."""

        # Upsert is part of the automated regression suite.
        def upsert(self, *, collection_name, points):
            """Store the collection name and points for payload assertions."""
            captured["collection"] = collection_name
            captured["points"] = points

    monkeypatch.setattr(vector_store, "ensure_collection", lambda: None)
    monkeypatch.setattr(vector_store, "get_client", lambda: _Client())
    monkeypatch.setattr(vector_store, "reset_sparse_index", lambda: None)
    chunk = RetrievedChunk(
        text="Mounted ConfigMaps update eventually.",
        source="configmap.html",
        metadata={
            "document_id": "doc-1",
            "authority_tier": "true",
            "chunk_index": 0,
            "total_chunks": 1,
            "ingestion_version": "v2",
        },
    )

    vector_store.upsert_chunks([chunk], [[0.1, 0.2]])

    payload = captured["points"][0].payload
    assert payload["source"] == "configmap.html"
    assert payload["text"] == chunk.text
    assert payload["document_id"] == "doc-1"
    assert payload["authority_tier"] == "true"
    assert payload["ingestion_version"] == "v2"


# Note: Verifies test hybrid search boosts sparse troubleshooting hits so future changes cannot silently break this expected behavior.
def test_hybrid_search_boosts_sparse_troubleshooting_hits(monkeypatch):
    """Verify that hybrid search boosts sparse troubleshooting hits.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    monkeypatch.setattr(
        vector_store,
        "search",
        lambda embedding, top_k=5: [
            RetrievedChunk(
                text="General memory debugging notes from an unrelated PDF.",
                source="Modern C v2 (2019).pdf",
                score=0.9,
                retrieval_score=0.9,
            )
        ],
    )
    monkeypatch.setattr(
        vector_store,
        "sparse_search",
        lambda query, top_k=5: [
            RetrievedChunk(
                text="Troubleshooting Pods: ErrImagePull means the image could not be pulled from the registry.",
                source="troubleshooting-pods.html",
                metadata={"authority_tier": "true"},
                score=0.2,
                retrieval_score=0.2,
            )
        ],
    )

    ranked = vector_store.hybrid_search(
        query_embedding=[0.0],
        query="What does error ErrImagePull mean and how do I fix it?",
        top_k=2,
    )

    assert ranked[0].source == "troubleshooting-pods.html"
    assert ranked[0].metadata["authority_tier"] == "true"


# Note: Verifies test hybrid search boosts runbook sources for operational queries so future changes cannot silently break this expected behavior.
def test_hybrid_search_boosts_runbook_sources_for_operational_queries(monkeypatch):
    """Verify that hybrid search boosts runbook sources for operational queries.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    monkeypatch.setattr(
        vector_store,
        "search",
        lambda embedding, top_k=5: [
            RetrievedChunk(
                text="A generic article that mentions escalation in passing.",
                source="Some Unrelated Book.pdf",
                score=0.95,
                retrieval_score=0.95,
            )
        ],
    )
    monkeypatch.setattr(
        vector_store,
        "sparse_search",
        lambda query, top_k=5: [
            RetrievedChunk(
                text="On-Call Escalation Policy for P1 incidents with ack times and bridge requirements.",
                source="oncall-escalation-policy.html",
                score=0.15,
                retrieval_score=0.15,
            )
        ],
    )

    ranked = vector_store.hybrid_search(
        query_embedding=[0.0],
        query="What does our escalation policy say for P1 incidents?",
        top_k=2,
    )

    assert ranked[0].source == "oncall-escalation-policy.html"


# Note: Verifies test expanded sparse query maps errimagepull to image pull terms so future changes cannot silently break this expected behavior.
def test_expanded_sparse_query_maps_errimagepull_to_image_pull_terms():
    """Verify that expanded sparse query maps errimagepull to image pull terms.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    expanded = vector_store._expanded_sparse_query(  # noqa: SLF001
        "What does error ErrImagePull mean and how do I fix it?"
    ).lower()

    assert "errimagepull" in expanded
    assert "imagepullbackoff" in expanded
    assert "image" in expanded
    assert "pull" in expanded


# Note: Verifies test expanded sparse query maps oomkilled to memory terms so future changes cannot silently break this expected behavior.
def test_expanded_sparse_query_maps_oomkilled_to_memory_terms():
    """Verify that expanded sparse query maps oomkilled to memory terms.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    expanded = vector_store._expanded_sparse_query(  # noqa: SLF001
        "Find the runbook that mentions OOMKilled"
    ).lower()

    assert "oomkilled" in expanded
    assert "oom" in expanded
    assert "killed" in expanded
    assert "memory" in expanded


# Note: Verifies test sparse search rescues imagepullbackoff document so future changes cannot silently break this expected behavior.
def test_sparse_search_rescues_imagepullbackoff_document(monkeypatch):
    """Verify that sparse search rescues imagepullbackoff document.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    # Note: Fake index is part of the automated regression suite.
    class _FakeIndex:
        # Note: Supports init as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake index within the automated regression suite.

        Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        # Note: Init is part of the automated regression suite.
        def __init__(self):
            """Initialize init dependencies and runtime state.

            Note:
                Explicit initialization keeps object construction predictable and testable.
            """
            self.documents = [
                {
                    "source": "troubleshooting-pods.html",
                    "text": "Troubleshooting Pods: ImagePullBackOff means the image could not be pulled from the registry.",
                },
                {
                    "source": "Unrelated.pdf",
                    "text": "General error handling discussion from an unrelated paper.",
                },
            ]

        # Note: Supports search as reusable test setup so scenarios stay deterministic and readable.
        def search(self, query: str, top_k: int = 5):
            """Perform search for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return [
                RetrievedChunk(
                    text="General error handling discussion from an unrelated paper.",
                    source="Unrelated.pdf",
                    score=0.6,
                    retrieval_score=0.6,
                )
            ]

    monkeypatch.setattr(vector_store, "_get_sparse_index", lambda: _FakeIndex())

    ranked = vector_store.sparse_search(
        "What does error ErrImagePull mean and how do I fix it?",
        top_k=2,
    )

    assert ranked[0].source == "troubleshooting-pods.html"


# Note: Verifies test hybrid search promotes only strong troubleshooting matches so future changes cannot silently break this expected behavior.
def test_hybrid_search_promotes_only_strong_troubleshooting_matches(monkeypatch):
    """Verify that hybrid search promotes only strong troubleshooting matches.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    monkeypatch.setattr(
        vector_store,
        "search",
        lambda embedding, top_k=5: [
            RetrievedChunk(
                text="General error handling discussion from an unrelated systems paper.",
                source="Unrelated.pdf",
                score=0.97,
                retrieval_score=0.97,
            ),
            RetrievedChunk(
                text="Pods can enter ImagePullBackOff if the registry image tag is wrong.",
                source="k8s-troubleshooting.html",
                score=0.45,
                retrieval_score=0.45,
            ),
        ],
    )
    monkeypatch.setattr(
        vector_store,
        "sparse_search",
        lambda query, top_k=5: [
            RetrievedChunk(
                text="Pods can enter ImagePullBackOff if the registry image tag is wrong.",
                source="k8s-troubleshooting.html",
                score=0.3,
                retrieval_score=0.3,
            ),
            RetrievedChunk(
                text="General error handling discussion from an unrelated systems paper.",
                source="Unrelated.pdf",
                score=0.29,
                retrieval_score=0.29,
            ),
        ],
    )

    ranked = vector_store.hybrid_search(
        query_embedding=[0.0],
        query="What does error ErrImagePull mean and how do I fix it?",
        top_k=1,
    )

    assert ranked[0].source == "k8s-troubleshooting.html"
