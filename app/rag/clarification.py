"""Detect underspecified questions before they can retrieve misleading evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SUPPORTED_TARGETS = (
    "kubernetes",
    "configmap",
    "secret",
    "pod",
    "deployment",
    "statefulset",
    "daemonset",
    "service",
    "ingress",
    "namespace",
    "serviceaccount",
    "service account",
    "rbac",
    "node",
    "cluster",
    "kubectl",
    "incident response runbook",
    "on-call escalation policy",
)

_AMBIGUOUS_ACTIONS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bscal(?:e|ing)\b", re.IGNORECASE),
        "scaling",
        "What do you want to scale: a Kubernetes Deployment, StatefulSet, cluster, or another resource?",
    ),
    (
        re.compile(r"\bdeploy(?:ment|ing)?\b", re.IGNORECASE),
        "deployment",
        "What do you want to deploy, and is the target a Kubernetes Deployment, Job, or StatefulSet?",
    ),
    (
        re.compile(r"\brestart\b", re.IGNORECASE),
        "restart",
        "What should be restarted: a Pod, Deployment, node, service, or another component?",
    ),
    (
        re.compile(r"\bsecure\b", re.IGNORECASE),
        "security",
        "What do you want to secure, for example a Kubernetes cluster, workload, Secret, or network path?",
    ),
    (
        re.compile(r"\bmonitor\b", re.IGNORECASE),
        "monitoring",
        "What do you want to monitor: a Kubernetes cluster, workload, Pod, or application metric?",
    ),
    (
        re.compile(r"\bback\s+(?:it|this|that)\s+up\b", re.IGNORECASE),
        "backup",
        "What needs to be backed up: Kubernetes resources, persistent volumes, or a database?",
    ),
    (
        re.compile(
            r"\b(?:make\s+(?:it|this|that)\s+(?:respond\s+)?faster|"
            r"why\s+is\s+(?:it|this|that)\s+slow)\b",
            re.IGNORECASE,
        ),
        "performance",
        "Which Kubernetes workload or component is slow, and what symptom or metric are you observing?",
    ),
    (
        re.compile(
            r"\b(?:best\s+architecture|what\s+architecture\s+should\s+i\s+use)\b",
            re.IGNORECASE,
        ),
        "architecture",
        "What system or workload needs an architecture recommendation, and what constraints matter?",
    ),
    (
        re.compile(r"\bmake\s+(?:it|this|that)\s+bigger\b", re.IGNORECASE),
        "sizing",
        "What resource should be made larger: a workload replica count, Pod resources, node pool, or volume?",
    ),
    (
        re.compile(r"\bmake\s+(?:it|this|that)\s+private\b", re.IGNORECASE),
        "privacy",
        "What resource or traffic path should become private, who should retain access, and which environment is affected?",
    ),
    (
        re.compile(r"\b(?:rotate|revoke)\s+(?:it|this|that)\b", re.IGNORECASE),
        "credential_action",
        "What credential, Secret, certificate, key, or access grant should be changed, which environment is affected, and do you want instructions or an authorized action?",
    ),
    (
        re.compile(
            r"\b(?:roll\s*back|rollback|roll\s+(?:it|this|that)\s+back|revert)\b",
            re.IGNORECASE,
        ),
        "rollback",
        "What resource or release do you want rolled back, which environment does it affect, "
        "what revision should it target, and do you want instructions or authorization to perform it?",
    ),
    (
        re.compile(
            r"\b(?:restore|recover)\s+(?:it|this|that|the\s+(?:previous|prior|old)\s+one)\b",
            re.IGNORECASE,
        ),
        "restore",
        "What workload, configuration, data object, credential, or release should be restored, "
        "which environment and previous version do you mean, and do you want instructions or "
        "authorization for an actual change?",
    ),
    (
        re.compile(r"^\s*what\s+changed\s*\??\s*$", re.IGNORECASE),
        "change_scope",
        "What system, resource, deployment, or time period do you want to compare?",
    ),
    (
        re.compile(r"\broll\s+(?:it|this|that)\s+back\b", re.IGNORECASE),
        "rollback",
        "What resource or release should be rolled back, in which environment, and to which revision?",
    ),
)


@dataclass(frozen=True)
class ClarificationDecision:
    """Immutable record of a detected ambiguity: why clarification is needed, the
    follow-up prompt to show the user, and a short category label for the
    ambiguity (e.g. "scaling", "rollback", "credential_action")."""

    reason: str
    prompt: str
    ambiguity_type: str


def detect_clarification_need(question: str) -> ClarificationDecision | None:
    """Return a clarification request for short actions without a supported target.

    Explicit Kubernetes entities bypass clarification. Conversation rewriting runs
    before this function, so a successfully resolved follow-up also contains its
    target and proceeds normally.
    """
    cleaned = " ".join((question or "").split()).strip()
    lowered = cleaned.lower()
    if not cleaned or any(target in lowered for target in _SUPPORTED_TARGETS):
        return None

    token_count = len(re.findall(r"[a-z0-9]+", lowered))
    unresolved_reference = bool(re.search(r"\b(it|this|that)\b", lowered))

    for pattern, ambiguity_type, prompt in _AMBIGUOUS_ACTIONS:
        if pattern.search(cleaned) and (token_count <= 12 or unresolved_reference):
            return ClarificationDecision(
                reason=(
                    f"underspecified_{ambiguity_type}: the request does not identify "
                    "a supported Kubernetes target"
                ),
                prompt=prompt,
                ambiguity_type=ambiguity_type,
            )
    return None
