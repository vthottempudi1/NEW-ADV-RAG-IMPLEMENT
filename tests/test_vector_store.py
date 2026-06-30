from app.models import RetrievedChunk
from app.services import vector_store


def test_hybrid_search_boosts_sparse_troubleshooting_hits(monkeypatch):
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


def test_hybrid_search_boosts_runbook_sources_for_operational_queries(monkeypatch):
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


def test_expanded_sparse_query_maps_errimagepull_to_image_pull_terms():
    expanded = vector_store._expanded_sparse_query(  # noqa: SLF001
        "What does error ErrImagePull mean and how do I fix it?"
    ).lower()

    assert "errimagepull" in expanded
    assert "imagepullbackoff" in expanded
    assert "image" in expanded
    assert "pull" in expanded


def test_expanded_sparse_query_maps_oomkilled_to_memory_terms():
    expanded = vector_store._expanded_sparse_query(  # noqa: SLF001
        "Find the runbook that mentions OOMKilled"
    ).lower()

    assert "oomkilled" in expanded
    assert "oom" in expanded
    assert "killed" in expanded
    assert "memory" in expanded


def test_sparse_search_rescues_imagepullbackoff_document(monkeypatch):
    class _FakeIndex:
        def __init__(self):
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

        def search(self, query: str, top_k: int = 5):
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


def test_hybrid_search_promotes_only_strong_troubleshooting_matches(monkeypatch):
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
