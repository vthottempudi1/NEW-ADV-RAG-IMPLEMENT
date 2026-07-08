from app.services.rag_service import _prefer_local_corpus


def test_generic_kubernetes_question_does_not_disable_web_fallback():
    assert _prefer_local_corpus("What are the steps to deploy ArgoCD on a fresh Kubernetes cluster?") is False


def test_org_specific_runbook_question_prefers_local_corpus():
    assert _prefer_local_corpus("What does our runbook say for P1 incidents?") is True
