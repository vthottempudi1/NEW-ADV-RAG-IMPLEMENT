from app.models import RetrievedChunk
from app.services.reranking import Reranker


class _FakeModel:
    def predict(self, pairs):
        return [-8.0, 1.0]


def test_reranker_preserves_strong_lexical_match_when_model_is_misleading():
    reranker = Reranker.__new__(Reranker)
    reranker.model = _FakeModel()

    chunks = [
        RetrievedChunk(
            text=(
                "P1 incidents require immediate escalation. "
                "The primary on-call engineer must acknowledge within 5 minutes."
            ),
            source="oncall-escalation-policy.html",
            score=0.48,
            retrieval_score=0.48,
        ),
        RetrievedChunk(
            text="RBAC policy guidance discusses privilege escalation and access control.",
            source="rbac-good-practices.pdf",
            score=0.08,
            retrieval_score=0.08,
        ),
    ]

    reranked = reranker.rerank(
        "What does our escalation policy say for P1 incidents?",
        chunks,
        top_k=2,
    )

    assert reranked[0].source == "oncall-escalation-policy.html"
    assert reranked[0].score > reranked[1].score


def test_reranker_preserves_exact_operational_error_match():
    reranker = Reranker.__new__(Reranker)
    reranker.model = _FakeModel()

    chunks = [
        RetrievedChunk(
            text=(
                "If the image name is invalid or the registry credentials are missing, "
                "the pod can show ImagePullBackOff while Kubernetes retries pulling the image."
            ),
            source="troubleshooting-pods.html",
            score=0.55,
            retrieval_score=0.55,
        ),
        RetrievedChunk(
            text="General software systems can enter an error state and require restarting.",
            source="distributed-systems-notes.pdf",
            score=0.18,
            retrieval_score=0.18,
        ),
    ]

    reranked = reranker.rerank(
        "What does error ErrImagePull mean and how do I fix it?",
        chunks,
        top_k=2,
    )

    assert reranked[0].source == "troubleshooting-pods.html"
    assert reranked[0].score > reranked[1].score


def test_reranker_boosts_runbook_style_sources_for_oomkilled_queries():
    reranker = Reranker.__new__(Reranker)
    reranker.model = _FakeModel()

    chunks = [
        RetrievedChunk(
            text=(
                "Runbook: if a container is OOMKilled, inspect memory limits, requests, "
                "and recent node pressure events before restarting the workload."
            ),
            source="incident-response-runbook.html",
            score=0.44,
            retrieval_score=0.44,
        ),
        RetrievedChunk(
            text="Memory pressure can affect throughput in distributed compute systems.",
            source="systems-performance.pdf",
            score=0.21,
            retrieval_score=0.21,
        ),
    ]

    reranked = reranker.rerank(
        "Find the runbook that mentions OOMKilled",
        chunks,
        top_k=2,
    )

    assert reranked[0].source == "incident-response-runbook.html"
    assert reranked[0].score > reranked[1].score
