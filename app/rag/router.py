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


def classify_intent(question: str) -> Intent:
    """
    Classify a user question into one of three retrieval intents: 'sql', 'rag', or 'hybrid'.

    This is the zero-cost intent router — the first decision gate in the LangGraph
    orchestration pipeline. The returned Intent literal determines which downstream
    branch the LangGraph graph executes next:

        'rag'    → Qdrant Cloud vector search (dense, sparse, hybrid, HyDE, CRAG, or SRAG)
        'sql'    → Governed Text-to-SQL pipeline against RDS PostgreSQL, with sqlglot AST
                   validation and optional Human-in-the-Loop approval via LangGraph interrupt
        'hybrid' → Both pipelines execute; SQL structured data and RAG document context
                   are merged into a single answer before generation

    Classification Logic (rule-based, no LLM call, no cache read):
        1. SQL signal   — question matches a SQL-hint keyword regex (e.g. "how many",
                          "count", "average", "total") AND a SQL-entity regex (e.g. a
                          known table name, column, or Kubernetes operational metric noun
                          such as "incidents", "pods", "SLA breaches").
        2. Hybrid       — question satisfies the SQL signal AND additionally contains a
                          RAG-hint phrase (e.g. "explain", "summarize", "what does the
                          policy say") or a hybrid connector (e.g. "and also", "as well
                          as"), indicating the user needs both structured data and
                          document-grounded runbook/policy context.
        3. RAG (default)— no strong SQL signal detected; routes to Qdrant semantic
                          retrieval over the Kubernetes IT-Ops document corpus.

    Priority order: hybrid > sql > rag (hybrid fires first when both signals are present).

    Args:
        question (str): Raw natural-language question from the user or an upstream
                        LangGraph agent node, before any guardrail preprocessing.

    Returns:
        Intent: One of three string literals —
            'sql'    → hand off to SQL pipeline (RDS PostgreSQL via governed Text-to-SQL)
            'rag'    → hand off to retrieval pipeline (Qdrant Cloud vector search)
            'hybrid' → hand off to both; results merged before LLM generation

    Design Notes:
        - Pure rule-based: deterministic, zero-latency, no LLM token cost at routing time.
        - Runs after JWT auth and all 9 guardrail layers complete; intent classification
        only executes on requests that have already passed full security preprocessing.
        - Regex sets (_SQL_HINT_REGEXES, _SQL_ENTITY_REGEXES) and hint lists (_RAG_HINTS,
          _HYBRID_CONNECTORS) are compiled at module level — no recompilation per call.
        - The 'intent' cache namespace exists in Upstash Redis but this deterministic router
          does not read or write it; that tier is reserved for future LLM-based routing.
        - To tune routing for new Kubernetes entities or operational terms, extend
          _SQL_ENTITY_REGEXES or _RAG_HINTS without touching this function's logic.

    Examples:
        >>> classify_intent("How many P1 incidents were resolved last quarter?")
        'sql'
        >>> classify_intent("What does our escalation policy say for P1 incidents?")
        'rag'
        >>> classify_intent("How many P1 incidents breached SLA last month and what is our escalation policy?")
        'hybrid'
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
