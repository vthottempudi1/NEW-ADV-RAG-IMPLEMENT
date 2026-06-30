from typing import Literal


Intent = Literal["sql", "rag", "hybrid"]


_SQL_HINTS = (
    "how many",
    "count",
    "total",
    "average",
    "avg",
    "list all",
    "show all",
    "show users",
    "which user",
    "which users",
)

_RAG_HINTS = (
    "document",
    "documentation",
    "career",
    "roadmap",
    "guide",
    "skills",
    "roles",
    "summary",
    "explain",
    "what is this document about",
    "policy",
    "runbook",
    "playbook",
    "procedure",
    "best practice",
    "best practices",
    "recommendation",
    "recommendations",
    "guidance",
    "how should",
    "what should",
    "what does our",
    "what is our",
    "say about",
)

_HYBRID_CONNECTORS = (
    " and what ",
    " and how ",
    " and why ",
    " along with ",
    " based on our ",
)


def classify_intent(question: str) -> Intent:
    lowered = question.strip().lower()

    has_sql = any(hint in lowered for hint in _SQL_HINTS)
    has_rag = any(hint in lowered for hint in _RAG_HINTS)
    has_hybrid_connector = any(hint in lowered for hint in _HYBRID_CONNECTORS)

    if has_sql and (has_rag or has_hybrid_connector):
        return "hybrid"
    if has_sql:
        return "sql"
    return "rag"
