import re
from typing import Literal

Intent = Literal["sql", "rag", "hybrid"]


_SQL_HINT_PATTERNS = (
    r"\bhow many\b",
    r"\bcount\b",
    r"\btotal\b",
    r"\baverage\b",
    r"\bavg\b",
    r"\bmost\b",
    r"\bhighest\b",
    r"\bleast\b",
    r"\blist all\b",
    r"\bshow all\b",
    r"\bshow users\b",
    r"\bwhich\s+(?:cluster|on-?call engineer|incident|alert)\b",
    r"\bshow me details\b",
    r"\bdetails for\b",
)

_SQL_ENTITY_PATTERNS = (
    r"\buser(?:s)?\b",
    r"\bincident(?:s)?\b",
    r"\balert(?:s)?\b",
    r"\bon-?call\b",
    r"\bengineer(?:s)?\b",
    r"\bpaged?\b",
    r"\bpages\b",
    r"\bcluster(?:s)?\b",
    r"\bsla\b",
    r"\bbreached\b",
    r"\bunresolved\b",
    r"\bresolved\b",
    r"\bopen\b",
    r"\bclosed\b",
    r"\bmonth\b",
    r"\bquarter\b",
    r"\bweek\b",
    r"\btoday\b",
    r"\byesterday\b",
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
    "best practice",
    "best practices",
    "rbac",
    "service account",
    "service accounts",
    "kubernetes",
)

_HYBRID_CONNECTORS = (
    " and what ",
    " and how ",
    " and why ",
    " along with ",
    " based on our ",
)

_SQL_HINT_REGEXES = tuple(re.compile(pattern) for pattern in _SQL_HINT_PATTERNS)
_SQL_ENTITY_REGEXES = tuple(re.compile(pattern) for pattern in _SQL_ENTITY_PATTERNS)


# Learner note: Decides classify intent, which controls the next branch of the application workflow.
def classify_intent(question: str) -> Intent:
    """Perform classify intent for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    lowered = question.strip().lower()

    has_sql_keyword = any(regex.search(lowered) for regex in _SQL_HINT_REGEXES)
    has_sql_entity = any(regex.search(lowered) for regex in _SQL_ENTITY_REGEXES)
    has_sql = has_sql_keyword and has_sql_entity
    has_rag = any(hint in lowered for hint in _RAG_HINTS)
    has_hybrid_connector = any(hint in lowered for hint in _HYBRID_CONNECTORS)

    if has_sql and (has_rag or has_hybrid_connector):
        return "hybrid"
    if has_sql:
        return "sql"
    return "rag"
