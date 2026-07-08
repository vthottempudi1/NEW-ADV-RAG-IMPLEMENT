from app.models import RetrievedChunk
from app.services.rag_service import (
    _drop_negative_rerank_tail,
    _drop_non_kubernetes_corpus_noise,
    _prefer_anchor_matched_sources,
    _prefer_entity_named_sources,
)


def test_anchor_filter_drops_unrelated_dashboard_chunk_for_configmap_secret_question():
    chunks = [
        RetrievedChunk(
            text="Kubernetes Dashboard lets you manage workloads through a web UI.",
            source="tasks__access-application-cluster__web-ui-dashboard.html",
            score=0.71,
            retrieval_score=0.71,
        ),
        RetrievedChunk(
            text="Secrets store sensitive data such as passwords and tokens.",
            source="concepts__configuration__secret.txt",
            score=0.69,
            retrieval_score=0.69,
        ),
        RetrievedChunk(
            text="ConfigMaps store non-confidential configuration in key-value pairs.",
            source="concepts__configuration__configmap.html",
            score=0.67,
            retrieval_score=0.67,
        ),
    ]

    filtered = _prefer_anchor_matched_sources(
        "What is the difference between a ConfigMap and a Secret in Kubernetes?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == [
        "concepts__configuration__secret.txt",
        "concepts__configuration__configmap.html",
    ]


def test_negative_rerank_tail_is_dropped_when_stronger_chunks_exist():
    chunks = [
        RetrievedChunk(text="good 1", source="doc1", score=0.9, retrieval_score=0.9, rerank_score=3.2),
        RetrievedChunk(text="good 2", source="doc2", score=0.8, retrieval_score=0.8, rerank_score=1.1),
        RetrievedChunk(text="bad", source="doc3", score=0.7, retrieval_score=0.7, rerank_score=-2.4),
    ]

    filtered = _drop_negative_rerank_tail(chunks)

    assert [chunk.source for chunk in filtered] == ["doc1", "doc2"]


def test_entity_named_sources_are_preferred_for_statefulset_follow_up():
    chunks = [
        RetrievedChunk(text="StatefulSets keep stable identities for Pods.", source="concepts__workloads__controllers__statefulset.docx", score=0.8, retrieval_score=0.8),
        RetrievedChunk(text="Node pressure eviction happens under resource stress.", source="concepts__scheduling-eviction__node-pressure-eviction.docx", score=0.7, retrieval_score=0.7),
        RetrievedChunk(text="Pods are the smallest deployable units.", source="concepts__workloads__pods.html", score=0.6, retrieval_score=0.6),
    ]

    filtered = _prefer_entity_named_sources(
        "Which one, StatefulSet or Deployment, would you use for a database, and why?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == [
        "concepts__workloads__controllers__statefulset.docx",
    ]


def test_non_kubernetes_noise_is_dropped_when_canonical_kubernetes_sources_exist():
    chunks = [
        RetrievedChunk(text="Secrets store passwords and tokens.", source="concepts__configuration__secret.txt", score=0.8, retrieval_score=0.8),
        RetrievedChunk(text="JWT secret hardcoded vulnerability example.", source="GPT-4 System Card.pdf", score=0.7, retrieval_score=0.7),
    ]

    filtered = _drop_non_kubernetes_corpus_noise(
        "Would you still use a Secret for a database password, or would you combine it with something else in Kubernetes?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == [
        "concepts__configuration__secret.txt",
    ]
