from __future__ import annotations

import re

_DOCUMENT_CLAUSE_PATTERNS = (
    r"\band\s+(what does (?:our|the) .+)$",
    r"\band\s+(what is (?:our|the) .+)$",
    r"\band\s+(how should (?:we|i) .+)$",
    r"\band\s+(how do (?:we|i) .+)$",
    r"\band\s+(what should (?:we|i) .+)$",
)


# Learner note: Produces a document-only question so SQL language cannot dilute RAG, HyDE, reranking, or CRAG relevance.
def derive_hybrid_rag_question(question: str) -> str:
    """Extract the documentation clause from a combined SQL plus RAG question.

    SQL still receives the original question. Retrieval, HyDE, reranking, and CRAG
    receive this focused form so database vocabulary cannot attract noisy chunks.
    """
    cleaned = " ".join((question or "").split()).strip()
    lowered = cleaned.lower()

    if "mttr" in lowered and any(term in lowered for term in ("reduce", "improve", "lower")):
        return (
            "What does our incident response runbook recommend for reducing MTTR, "
            "including alert triage, rollback readiness, observability, and ownership?"
        )

    if "runbook" in lowered and any(
        term in lowered for term in ("do first", "first step", "first response", "start")
    ):
        severity = "P2 " if "p2" in lowered else ""
        return (
            f"What are the first response steps in our incident response runbook for "
            f"{severity}alerts and production incidents?"
        )

    if "remediation" in lowered or "procedure" in lowered:
        return (
            "What is the standard remediation procedure in our incident response runbook "
            "for unresolved production incidents?"
        )

    is_incident_policy = "policy" in lowered and any(
        term in lowered
        for term in ("on-call", "oncall", "incident", "p1", "p2", "sla", "escalation")
    )
    if "escalation" in lowered or is_incident_policy:
        severity = "P1 " if "p1" in lowered else ""
        sla = " that breach SLA" if "sla" in lowered else ""
        return f"What does our on-call escalation policy require for {severity}incidents{sla}?"

    for pattern in _DOCUMENT_CLAUSE_PATTERNS:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            clause = match.group(1).strip().rstrip("?")
            return f"According to our internal documentation, {clause}?"

    return cleaned
