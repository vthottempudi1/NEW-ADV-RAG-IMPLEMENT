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
    "career",
    "roadmap",
    "guide",
    "skills",
    "roles",
    "summary",
    "explain",
    "what is this document about",
)


def classify_intent(question: str) -> Intent:
    lowered = question.strip().lower()

    has_sql = any(hint in lowered for hint in _SQL_HINTS)
    has_rag = any(hint in lowered for hint in _RAG_HINTS)

    if has_sql and has_rag:
        return "hybrid"
    if has_sql:
        return "sql"
    return "rag"