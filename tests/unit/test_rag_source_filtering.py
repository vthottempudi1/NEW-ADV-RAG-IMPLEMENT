from app.models import RetrievedChunk
from app.rag import service as rag_service_module

#from app.rag.service import _prefer_authoritative_chunks
from app.rag.service import (
    _augment_security_evidence,
    _augment_workload_identity_evidence,
    _authoritative_planned_evidence,
    _drop_dashboard_catalog_noise,
    _drop_negative_rerank_tail,
    _drop_non_kubernetes_corpus_noise,
    _ensure_planned_evidence,
    _evidence_plan,
    _merge_same_source_evidence,
    _planned_answer_guidance,
    _prefer_anchor_matched_sources,
    _prefer_authoritative_chunks,
    _prefer_entity_named_sources,
    _prefer_implicit_stateful_sources,
    _prefer_operational_sources,
    _prefer_security_sources,
    _prefer_service_discovery_sources,
    _requires_current_web_evidence,
)


# Test network policy plan requests complementary same source passages is part of the automated regression suite.
def test_network_policy_plan_requests_complementary_same_source_passages():
    """Composite policy answers need rules, additivity, and enforcement evidence."""
    plan = _evidence_plan(
        "Only frontend Pods may call payments on TCP 8443 and payments must not initiate egress."
    )
    assert len(plan) == 3
    assert all(pattern.search("concepts__services-networking__network-policies.html") for pattern, _ in plan)


# Test https request plan covers service identity and ready routing is part of the automated regression suite.
def test_https_request_plan_covers_service_identity_and_ready_routing():
    """HTTPS tracing needs both stable Service identity and ready-backend routing evidence."""
    plan = _evidence_plan(
        "Trace an external HTTPS request from the edge to a ready application Pod."
    )
    service_queries = [
        query for pattern, query in plan
        if pattern.search("concepts__services-networking__service.txt")
    ]
    assert len(service_queries) == 2
    assert any("stable network endpoint" in query for query in service_queries)
    assert any("healthy ready backend" in query for query in service_queries)


# Test daemonset plan covers node ownership and gpu placement is part of the automated regression suite.
def test_daemonset_plan_covers_node_ownership_and_gpu_placement():
    """A restricted node-wide agent needs evidence for ownership and placement."""
    plan = _evidence_plan(
        "We need a security agent on every GPU worker but nowhere else. Which controller and scheduling constraint should we use?"
    )

    assert len(plan) == 2
    assert all(pattern.search("concepts__workloads__controllers__daemonset.html") for pattern, _ in plan)
    assert any("eligible nodes" in query for _, query in plan)
    assert any("nodeSelector" in query for _, query in plan)


# Test secret plan requests pod credential usage evidence is part of the automated regression suite.
def test_secret_plan_requests_pod_credential_usage_evidence():
    """Secret evidence should describe Pod credential use, not merely Secret types."""
    plan = _evidence_plan(
        "A Pod needs one database credential and permission to read only that Secret. Describe the identity and authorization design."
    )

    secret_queries = [query for pattern, query in plan if pattern.search("concepts__configuration__secret.txt")]
    assert secret_queries == [
        "Secrets provide credentials passwords to Pods environment variables secretKeyRef"
    ]


# Test sealed v2 finding plans cover required authoritative evidence is part of the automated regression suite.
def test_sealed_v2_finding_plans_cover_required_authoritative_evidence():
    """Generalized evidence plans reproduce each consumed sealed-v2 retrieval finding."""
    cases = {
        "A newly created Pod has no node assigned yet. Which component makes placement and which starts containers?": 3,
        "Which boundaries does a namespace provide, and why is it not a complete security boundary?": 2,
        "Compare the Privileged, Baseline, and Restricted Pod Security Standards.": 2,
        "Why use a dedicated ServiceAccount and short-lived projected tokens instead of a long-lived token?": 3,
        "A Pod remains Pending. Give a kubectl investigation for scheduling versus startup.": 4,
    }

    for question, expected_count in cases.items():
        assert len(_evidence_plan(question)) == expected_count


# Test challenge regression plans cover oom and serviceaccount evidence is part of the automated regression suite.
def test_challenge_regression_plans_cover_oom_and_serviceaccount_evidence():
    """Adversarial source requests and rationale questions retain authoritative evidence."""
    oom_plan = _evidence_plan(
        "Use a Python article, not cluster docs: what should I inspect after OOMKilled?"
    )
    identity_plan = _evidence_plan(
        "The default ServiceAccount works. Why create a dedicated one and limit its permissions?"
    )

    assert len(oom_plan) == 3
    assert len(identity_plan) == 2
    assert any(pattern.search("incident-response-runbook.html") for pattern, _ in oom_plan)
    assert any(pattern.search("rbac-good-practices.pdf") for pattern, _ in identity_plan)


# Test narrow security comparisons receive grounded synthesis guidance is part of the automated regression suite.
def test_narrow_security_comparisons_receive_grounded_synthesis_guidance():
    """Correct evidence must not be expanded into undocumented security claims."""
    namespace_guidance = _planned_answer_guidance(
        "Why is a namespace not a complete security boundary?"
    )
    pss_guidance = _planned_answer_guidance(
        "Compare Privileged, Baseline, and Restricted Pod Security Standards."
    )

    assert "RBAC is a key access-control mechanism" in namespace_guidance
    assert "Do not invent profile definitions" in pss_guidance


# Test authoritative plan preserves distinct chunks from same source is part of the automated regression suite.
def test_authoritative_plan_preserves_distinct_chunks_from_same_source(monkeypatch):
    """Multiple evidence requirements in one document must not collapse to one passage."""
    chunks = [
        RetrievedChunk(
            text="NetworkPolicy podSelector ingress TCP port egress isolation.",
            source="concepts__services-networking__network-policies.html",
            score=0.9,
        ),
        RetrievedChunk(
            text="Network policies are additive and combine allowed connections.",
            source="concepts__services-networking__network-policies.html",
            score=0.8,
        ),
        RetrievedChunk(
            text="A supporting network plugin must enforce NetworkPolicy.",
            source="concepts__services-networking__network-policies.html",
            score=0.7,
        ),
    ]
    monkeypatch.setattr(rag_service_module, "sparse_search", lambda query, top_k: chunks)

    selected = _authoritative_planned_evidence(
        "Only frontend Pods may call payments on TCP 8443 and payments must not initiate egress."
    )

    assert len(selected) == 3
    assert len({chunk.text for chunk in selected}) == 3


# Test planned passages from one source merge without losing evidence is part of the automated regression suite.
def test_planned_passages_from_one_source_merge_without_losing_evidence():
    """Fragmented authoritative passages should count as one coherent source context."""
    chunks = [
        RetrievedChunk(text="kubectl get pods and describe pods", source="kubectl.txt", score=0.4),
        RetrievedChunk(text="kubectl get warning events", source="kubectl.txt", score=0.6),
        RetrievedChunk(text="The scheduler selects a feasible node", source="scheduler.pdf", score=0.5),
    ]

    merged = _merge_same_source_evidence(chunks)

    assert len(merged) == 2
    assert "describe pods" in merged[0].text
    assert "warning events" in merged[0].text
    assert merged[0].score == 0.6


# Test composite identity plan reserves all required source families is part of the automated regression suite.
def test_composite_identity_plan_reserves_all_required_source_families():
    """Verify Secret, ServiceAccount, and RBAC evidence all survive final top-k selection."""
    chunks = [
        RetrievedChunk(text="noise", source="concepts__workloads__pods.html", score=0.99),
        RetrievedChunk(text="secret", source="concepts__configuration__secret.txt", score=0.8),
        RetrievedChunk(text="account", source="tasks__configure-pod-container__configure-service-account.txt", score=0.7),
        RetrievedChunk(text="rbac", source="concepts__security__rbac-good-practices.pdf", score=0.6),
    ]
    selected = _ensure_planned_evidence(
        "A Pod needs one Secret. Describe its ServiceAccount identity and authorization.",
        chunks,
        3,
    )
    assert [chunk.source for chunk in selected] == [
        "concepts__configuration__secret.txt",
        "tasks__configure-pod-container__configure-service-account.txt",
        "concepts__security__rbac-good-practices.pdf",
    ]


# Test broad Kubernetes security retrieval must retain RBAC and overview evidence is part of the automated regression suite.
def test_security_policy_prefers_canonical_security_sources():
    """Verify that unrelated PDFs cannot displace security and RBAC documentation."""
    chunks = [
        RetrievedChunk(text="general security", source="concepts__security__overview.txt"),
        RetrievedChunk(text="least privilege", source="concepts__security__rbac-good-practices.pdf"),
        RetrievedChunk(text="unrelated research", source="security-research-noise.pdf"),
    ]

    filtered = _prefer_security_sources("How do I secure a Kubernetes cluster?", chunks)

    assert [chunk.source for chunk in filtered] == [
        "concepts__security__overview.txt",
        "concepts__security__rbac-good-practices.pdf",
    ]


# Test security rescue must add missing RBAC evidence without duplicating chunks is part of the automated regression suite.
def test_security_evidence_rescue_adds_rbac_document(monkeypatch):
    """Verify broad security questions receive deterministic least-privilege evidence."""
    overview = RetrievedChunk(text="cluster security overview", source="concepts__security__overview.txt")
    rbac = RetrievedChunk(text="RBAC least privilege", source="concepts__security__rbac-good-practices.pdf")
    monkeypatch.setattr(rag_service_module, "sparse_search", lambda query, top_k: [rbac])

    merged = _augment_security_evidence("How do I secure a Kubernetes cluster?", [overview])

    assert [chunk.source for chunk in merged] == [overview.source, rbac.source]


# Test literal anchor filtering must not remove complementary RBAC evidence is part of the automated regression suite.
def test_security_question_preserves_rbac_during_anchor_filtering():
    """Verify broad security questions retain overview and least-privilege chunks."""
    chunks = [
        RetrievedChunk(text="secure the cluster API", source="concepts__security__overview.txt"),
        RetrievedChunk(text="RBAC least privilege roles", source="concepts__security__rbac-good-practices.pdf"),
    ]

    filtered = _prefer_anchor_matched_sources(
        "Tell me how to secure a Kubernetes cluster.",
        chunks,
    )

    assert filtered == chunks


# ServiceAccount authorization questions need configuration and RBAC evidence.
def test_workload_identity_rescue_adds_service_account_document(monkeypatch):
    """Verify dedicated identity configuration is rescued for least-privilege questions."""
    rbac = RetrievedChunk(text="least privilege RBAC", source="concepts__security__rbac-good-practices.pdf")
    service_account = RetrievedChunk(
        text="set serviceAccountName on the Pod",
        source="tasks__configure-pod-container__configure-service-account.txt",
    )
    monkeypatch.setattr(
        rag_service_module,
        "sparse_search",
        lambda query, top_k: [service_account],
    )

    merged = _augment_workload_identity_evidence(
        "How should ServiceAccounts use least-privilege RBAC?",
        [rbac],
    )

    assert [chunk.source for chunk in merged] == [rbac.source, service_account.source]


# Implicit database requirements must map to the StatefulSet controller.
def test_implicit_stateful_policy_removes_generic_single_instance_example():
    """Verify that stable database identity selects StatefulSet evidence."""
    chunks = [
        RetrievedChunk(text="stable identity", source="concepts__workloads__controllers__statefulset.docx"),
        RetrievedChunk(text="single instance", source="tasks__run-application__run-single-instance-stateful-application.pdf"),
    ]

    filtered = _prefer_implicit_stateful_sources(
        "What should run my database if it needs the same name and disk after rescheduling?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == [
        "concepts__workloads__controllers__statefulset.docx"
    ]


# Web fallback is reserved for explicitly current external-product questions.
def test_current_web_policy_blocks_static_kubernetes_questions():
    """Verify that static local topics cannot trigger third-party web fallback."""
    assert not _requires_current_web_evidence(
        "How do the Kubernetes control plane components work together?"
    )
    assert _requires_current_web_evidence(
        "What Kubernetes versions are currently supported by Amazon EKS?"
    )


# Verifies test anchor filter drops unrelated dashboard chunk for configmap secret question so future changes cannot silently break this expected behavior.
def test_anchor_filter_drops_unrelated_dashboard_chunk_for_configmap_secret_question():
    """Verify that anchor filter drops unrelated dashboard chunk for configmap secret question.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
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


# One authoritative storage chunk is enough to reject dashboard catalog noise.
def test_dashboard_noise_is_removed_when_one_relevant_source_survives():
    """Verify unrelated Dashboard evidence cannot accompany a storage answer."""
    chunks = [
        RetrievedChunk(text="web interface", source="tasks__access-application-cluster__web-ui-dashboard.html"),
        RetrievedChunk(text="persistent volumes", source="concepts__storage__persistent-volumes.pdf"),
    ]

    filtered = _drop_dashboard_catalog_noise(chunks, "Explain Kubernetes persistent storage")

    assert [chunk.source for chunk in filtered] == ["concepts__storage__persistent-volumes.pdf"]


# Verifies test negative rerank tail is dropped when stronger chunks exist so future changes cannot silently break this expected behavior.
def test_negative_rerank_tail_is_dropped_when_stronger_chunks_exist():
    """Verify that negative rerank tail is dropped when stronger chunks exist.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    chunks = [
        RetrievedChunk(text="good 1", source="doc1", score=0.9, retrieval_score=0.9, rerank_score=3.2),
        RetrievedChunk(text="good 2", source="doc2", score=0.8, retrieval_score=0.8, rerank_score=1.1),
        RetrievedChunk(text="bad", source="doc3", score=0.7, retrieval_score=0.7, rerank_score=-2.4),
    ]

    filtered = _drop_negative_rerank_tail(chunks)

    assert [chunk.source for chunk in filtered] == ["doc1", "doc2"]


# Verifies test entity named sources are preferred for statefulset follow up so future changes cannot silently break this expected behavior.
def test_entity_named_sources_are_preferred_for_statefulset_follow_up():
    """Verify that entity named sources are preferred for statefulset follow up.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
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


# Verifies test non kubernetes noise is dropped when canonical kubernetes sources exist so future changes cannot silently break this expected behavior.
def test_non_kubernetes_noise_is_dropped_when_canonical_kubernetes_sources_exist():
    """Verify that non kubernetes noise is dropped when canonical kubernetes sources exist.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
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


# Verifies authoritative runbooks displace high-scoring research noise for operational questions.
def test_operational_source_filter_eliminates_noisy_pdfs_when_runbook_exists():
    """Verify that operational source filter eliminates noisy pdfs when runbook exists.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    chunks = [
        RetrievedChunk(text="Retry-rate research", source="HTM Research.pdf", score=0.99),
        RetrievedChunk(text="ClearCase region administration", source="ClearCase Guide.pdf", score=0.95),
        RetrievedChunk(
            text="MTTR improvement recommendations include faster alert triage and rollback readiness.",
            source="incident-response-runbook.html",
            score=0.72,
        ),
    ]

    filtered = _prefer_operational_sources(
        "What does our incident response runbook recommend for reducing MTTR?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == ["incident-response-runbook.html"]


# Verifies changing Pod IP questions retain Service discovery evidence and remove controller noise.
def test_service_discovery_filter_prefers_service_document_for_changing_pod_ips():
    """Verify that service discovery filter prefers service document for changing pod ips.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    chunks = [
        RetrievedChunk(text="Stable Pod identity", source="statefulset.docx", score=0.95),
        RetrievedChunk(
            text="A Service exposes a stable endpoint for a changing set of Pods.",
            source="concepts__services-networking__service.txt",
            score=0.75,
        ),
    ]

    filtered = _prefer_service_discovery_sources(
        "How can clients find my application when its Pod IP addresses keep changing?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == [
        "concepts__services-networking__service.txt"
    ]


# Lay descriptions of replaced addresses must still resolve to Service discovery.
def test_service_discovery_filter_handles_durable_destination_paraphrase():
    """Verify a paraphrased stable-destination problem removes StatefulSet noise."""
    chunks = [
        RetrievedChunk(text="stable Pod identity", source="tutorials__stateful-application__basic-stateful-set.html"),
        RetrievedChunk(text="stable Service destination", source="concepts__services-networking__service.txt"),
    ]

    filtered = _prefer_service_discovery_sources(
        "Application instances get new addresses when replaced. What gives callers one durable destination?",
        chunks,
    )

    assert [chunk.source for chunk in filtered] == ["concepts__services-networking__service.txt"]

# Authoritative chunks handling for Hyde
def test_authority_filter_removes_noisy_sources_for_layman_question():
    """Verify that authoritative chunks displace explicitly noisy sources."""
    chunks = [
        RetrievedChunk(
            text="Use persistent volumes for durable workload storage.",
            source="concepts__storage__persistent-volumes.pdf",
            metadata={"authority_tier": "true"},
        ),
        RetrievedChunk(
            text="General research about durable file systems.",
            source="unrelated-storage-research.pdf",
            metadata={"authority_tier": "noisy"},
        ),
    ]

    filtered = _prefer_authoritative_chunks(chunks)

    assert [chunk.source for chunk in filtered] == [
        "concepts__storage__persistent-volumes.pdf"
    ]


def test_authority_filter_preserves_uploaded_documents():
    """Verify that the authority filter preserves user-uploaded documents."""
    chunks = [
        RetrievedChunk(
            text="Uploaded enterprise recovery policy.",
            source="recovery-policy.md",
            metadata={"authority_tier": "uploaded"},
        ),
        RetrievedChunk(
            text="Generic research document.",
            source="research-paper.pdf",
            metadata={"authority_tier": "noisy"},
        ),
    ]

    filtered = _prefer_authoritative_chunks(chunks)

    assert [chunk.source for chunk in filtered] == ["recovery-policy.md"]


def test_authority_filter_does_not_return_empty_when_metadata_is_missing():
    """Keep legacy chunks when authority metadata is unavailable."""
    chunks = [
        RetrievedChunk(
            text="Legacy document without authority metadata.",
            source="legacy-document.pdf",
        )
    ]

    assert _prefer_authoritative_chunks(chunks) == chunks


def test_authority_filter_rejects_explicitly_noisy_only_candidates():
    """Return no evidence instead of answering from a known noisy document."""
    chunks = [
        RetrievedChunk(
            text="Processor register acknowledgement behavior.",
            source="AMD-processor-register-reference.pdf",
            metadata={"authority_tier": "noisy"},
        )
    ]

    assert _prefer_authoritative_chunks(chunks) == []


def test_authority_filter_prefers_unclassified_legacy_over_explicit_noise():
    """Retain legacy unclassified evidence while removing explicit corpus noise."""
    legacy = RetrievedChunk(
        text="Legacy escalation policy evidence.",
        source="legacy-escalation-policy.html",
    )
    noisy = RetrievedChunk(
        text="Processor register acknowledgement behavior.",
        source="AMD-processor-register-reference.pdf",
        metadata={"authority_tier": "noisy"},
    )

    assert _prefer_authoritative_chunks([noisy, legacy]) == [legacy]
