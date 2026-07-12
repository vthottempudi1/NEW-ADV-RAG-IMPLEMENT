from app.rag.service import _prefer_local_corpus


# Learner note: Verifies test generic kubernetes question does not disable web fallback so future changes cannot silently break this expected behavior.
def test_generic_kubernetes_question_does_not_disable_web_fallback():
    """Verify that generic kubernetes question does not disable web fallback.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert _prefer_local_corpus("What are the steps to deploy ArgoCD on a fresh Kubernetes cluster?") is False


# Learner note: Verifies test org specific runbook question prefers local corpus so future changes cannot silently break this expected behavior.
def test_org_specific_runbook_question_prefers_local_corpus():
    """Verify that org specific runbook question prefers local corpus.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert _prefer_local_corpus("What does our runbook say for P1 incidents?") is True
