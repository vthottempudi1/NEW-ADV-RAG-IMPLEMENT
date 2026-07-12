from app.rag.service import _evidence_plan, _planned_answer_guidance, _prefer_local_corpus


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


# Learner Note: Test volume expansion plan reserves policy and workflow sources is part of the automated regression suite.
def test_volume_expansion_plan_reserves_policy_and_workflow_sources():
    """Require both StorageClass policy and PVC workflow evidence for expansion questions."""
    plan = _evidence_plan(
        "Which prerequisites allow a PVC expansion, and why should I not edit the PV directly?"
    )

    assert len(plan) == 2
    assert plan[0][0].search("concepts__storage__storage-classes.docx")
    assert plan[1][0].search("concepts__storage__persistent-volumes.pdf")


# Learner Note: Test multi part domain guidance requires complete supported answers is part of the automated regression suite.
def test_multi_part_domain_guidance_requires_complete_supported_answers():
    """Keep lifecycle, admission, and expansion synthesis complete without question-ID rules."""
    deployment = _planned_answer_guidance(
        "What stops when a Deployment is paused, what can change, and what does resume do?"
    )
    limits = _planned_answer_guidance(
        "What happens when a LimitRange minimum or maximum bound is violated?"
    )
    storage = _planned_answer_guidance(
        "What permits PVC expansion and why not edit the PersistentVolume?"
    )

    assert "each lifecycle part" in deployment
    assert "admission outcome" in limits
    assert "driver support" in storage


# Learner Note: General permission and unassigned-Pod questions reserve complementary evidence.
def test_v5_evidence_plans_cover_rbac_and_node_execution_responsibilities():
    """Require RBAC for ServiceAccount rights and kubelet evidence after scheduling."""
    identity = _evidence_plan(
        "A dedicated ServiceAccount has excessive permissions. Which authorization controls its rights?"
    )
    placement = _evidence_plan(
        "A Pod has no assigned node. Which component places it and which component runs it?"
    )

    assert any(pattern.search("concepts__security__rbac-good-practices.pdf") for pattern, _ in identity)
    assert any(pattern.search("concepts__overview__components.pdf") for pattern, _ in placement)


# Learner Note: V5 synthesis guidance prevents unsupported scheduling, probe, and paging explanations.
def test_v5_answer_guidance_limits_explanatory_overclaims():
    """Keep multi-part operational answers inside the exact retrieved evidence."""
    preemption = _planned_answer_guidance(
        "When can preemption help a high-priority Pod, and what does nomination mean?"
    )
    probes = _planned_answer_guidance(
        "What happens when readiness fails but liveness succeeds?"
    )
    paging = _planned_answer_guidance(
        "The P1 page is unacknowledged after joining the incident bridge. What remains?"
    )

    assert "Do not say that nomination reserves resources" in preemption
    assert "every possible traffic source" in probes
    assert "Do not invent why" in paging
