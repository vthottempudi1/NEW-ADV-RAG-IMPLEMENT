from app.models import RetrievedChunk
from app.rag import reranking as reranking_module
from app.rag.reranking import Reranker


# Learner Note: Model reuse protects request latency and memory under repeated reranking.
def test_reranker_reuses_cross_encoder_within_worker(monkeypatch):
    """Verify that repeated Reranker construction loads transformer weights once."""
    created: list[str] = []

    def _fake_loader(model_name: str):
        """Record model construction and return a deterministic fake encoder."""
        created.append(model_name)
        return _FakeModel()

    reranking_module._get_cross_encoder.cache_clear()
    monkeypatch.setattr(reranking_module, "CrossEncoder", _fake_loader)

    first = Reranker()
    second = Reranker()

    assert first.model is second.model
    assert created == [reranking_module.settings.reranker_model]
    reranking_module._get_cross_encoder.cache_clear()


# Learner Note: Fake model is part of the automated regression suite.
class _FakeModel:
    # Learner note: Supports predict as reusable test setup so scenarios stay deterministic and readable.
    """Represent fake model within the automated regression suite.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def predict(self, pairs):
        """Perform predict for the automated regression suite.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return [-8.0, 1.0]


# Learner note: Verifies test reranker preserves strong lexical match when model is misleading so future changes cannot silently break this expected behavior.
def test_reranker_preserves_strong_lexical_match_when_model_is_misleading():
    """Verify that reranker preserves strong lexical match when model is misleading.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
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


# Learner note: Verifies test reranker preserves exact operational error match so future changes cannot silently break this expected behavior.
def test_reranker_preserves_exact_operational_error_match():
    """Verify that reranker preserves exact operational error match.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
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


# Learner note: Verifies test reranker boosts runbook style sources for oomkilled queries so future changes cannot silently break this expected behavior.
def test_reranker_boosts_runbook_style_sources_for_oomkilled_queries():
    """Verify that reranker boosts runbook style sources for oomkilled queries.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
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
