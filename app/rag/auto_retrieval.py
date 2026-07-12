import re
from dataclasses import dataclass

_TROUBLESHOOTING_HINTS = (
    "error",
    "fix",
    "troubleshoot",
    "troubleshooting",
    "debug",
    "runbook",
    "incident",
    "oomkilled",
    "errimagepull",
    "imagepullbackoff",
    "crashloopbackoff",
    "logs",
    "log",
)
_GUIDANCE_HINTS = (
    "policy",
    "runbook",
    "playbook",
    "procedure",
    "guidance",
    "escalation",
    "what does our",
    "what is our",
    "best practice",
    "best practices",
)
_CONCEPTUAL_HINTS = (
    "mental model",
    "intuitively",
    "intuition",
    "conceptually",
    "conceptual",
    "easiest way to think about",
    "best way to think about",
    "how should i think about",
    "what are the different methods",
    "difference between",
    "compare",
    "overview",
    "basics",
)
_ACTION_HINTS = (
    "scale",
    "scaling",
    "replica",
    "replicas",
    "rollout",
    "restart",
    "deploy",
    "deployment",
    "describe",
    "cordon",
    "drain",
    "taint",
    "label",
    "annotate",
    "port-forward",
)
_ACTION_LEAD_HINTS = (
    "how do i",
    "how can i",
    "how to",
    "steps to",
    "step by step",
    "what do i do",
    "what should i do",
)
_REFLECTION_HINTS = (
    "not sure",
    "unsure",
    "root cause",
    "which signal should i trust",
    "which signal do i trust",
    "what should i check first",
    "where should i start",
    "step by step",
    "how should i troubleshoot",
)
_EXACT_TOKEN_HINTS = (
    "oomkilled",
    "errimagepull",
    "imagepullbackoff",
    "crashloopbackoff",
    "rbac",
    "serviceaccount",
    "service-account",
    "service account",
    "p1",
    "p2",
    "sla",
)
_SHORT_STOPWORDS = {
    "what",
    "why",
    "how",
    "is",
    "the",
    "this",
    "that",
    "our",
    "about",
    "does",
    "say",
    "for",
    "and",
    "with",
    "help",
}


# Learner Note: Auto retrieval decision is part of the retrieval-augmented generation pipeline.
@dataclass(frozen=True)
class AutoRetrievalDecision:
    """An immutable, explainable retrieval configuration for one request.

    Architecture Role:
        Gives the cache, LangGraph workflow, response metadata, and frontend one
        shared record of the requested mode and the strategy actually selected.
    Why Important:
        Reproducible decisions prevent cache collisions and make automatic feature
        activation visible to operators, evaluators, and hiring managers.
    """
    requested_search_mode: str
    resolved_search_mode: str
    enable_rerank: bool
    enable_hyde: bool
    enable_crag: bool
    enable_self_reflective: bool
    auto_enabled: bool
    auto_strategy_reason: str | None
    auto_applied_flags: list[str]

    # Learner note: Encapsulates cache context so this responsibility can be understood, tested, and changed independently.
    def cache_context(self, top_k: int) -> dict:
        """Perform cache context for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return {
            "top_k": top_k,
            "search_mode": self.resolved_search_mode,
            "enable_rerank": self.enable_rerank,
            "enable_hyde": self.enable_hyde,
            "enable_crag": self.enable_crag,
            "enable_self_reflective": self.enable_self_reflective,
        }

    # Learner note: Encapsulates graph flags so this responsibility can be understood, tested, and changed independently.
    def graph_flags(self, top_k: int) -> dict:
        """Perform graph flags for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return {
            "top_k": top_k,
            "search_mode": self.resolved_search_mode,
            "enable_rerank": self.enable_rerank,
            "enable_hyde": self.enable_hyde,
            "enable_crag": self.enable_crag,
            "enable_self_reflective": self.enable_self_reflective,
            "requested_search_mode": self.requested_search_mode,
            "resolved_enable_rerank": self.enable_rerank,
            "resolved_enable_hyde": self.enable_hyde,
            "resolved_enable_crag": self.enable_crag,
            "resolved_enable_self_reflective": self.enable_self_reflective,
            "auto_enabled": self.auto_enabled,
            "auto_strategy_reason": self.auto_strategy_reason,
            "auto_applied_flags": list(self.auto_applied_flags),
        }

    # Learner note: Encapsulates metadata so this responsibility can be understood, tested, and changed independently.
    def metadata(self) -> dict:
        """Perform metadata for the retrieval-augmented generation pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        return {
            "requested_search_mode": self.requested_search_mode,
            "resolved_search_mode": self.resolved_search_mode,
            "resolved_enable_rerank": self.enable_rerank,
            "resolved_enable_hyde": self.enable_hyde,
            "resolved_enable_crag": self.enable_crag,
            "resolved_enable_self_reflective": self.enable_self_reflective,
            "auto_enabled": self.auto_enabled,
            "auto_strategy_reason": self.auto_strategy_reason,
            "auto_applied_flags": list(self.auto_applied_flags),
        }


# Learner note: Encapsulates is vague query so this responsibility can be understood, tested, and changed independently.
def _is_vague_query(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is vague query.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    if len(tokens) <= 4:
        return True
    meaningful = [token for token in tokens if token not in _SHORT_STOPWORDS]
    return len(meaningful) <= 2


# Learner note: Encapsulates is semantic query so this responsibility can be understood, tested, and changed independently.
def _is_semantic_query(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is semantic query.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    if any(hint in lowered for hint in _CONCEPTUAL_HINTS):
        return True
    tokens = re.findall(r"[a-z0-9]+", lowered)
    return len(tokens) >= 12


# Learner note: Encapsulates has strong conceptual signal so this responsibility can be understood, tested, and changed independently.
def _has_strong_conceptual_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has strong conceptual signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    return any(hint in lowered for hint in _CONCEPTUAL_HINTS)


# Learner note: Encapsulates is direct object comparison so this responsibility can be understood, tested, and changed independently.
def _is_direct_object_comparison(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is direct object comparison.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    return ("difference between" in lowered or "compare" in lowered) and _has_exact_token_signal(question)


# Learner note: Encapsulates has exact token signal so this responsibility can be understood, tested, and changed independently.
def _has_exact_token_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has exact token signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    if any(hint in lowered for hint in _EXACT_TOKEN_HINTS):
        return True
    if "`" in question or '"' in question or "'" in question:
        return True
    for token in re.findall(r"[A-Za-z0-9_./:-]+", question):
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


# Learner note: Encapsulates has guidance signal so this responsibility can be understood, tested, and changed independently.
def _has_guidance_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has guidance signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    return any(hint in lowered for hint in _GUIDANCE_HINTS)


# Learner note: Encapsulates has troubleshooting signal so this responsibility can be understood, tested, and changed independently.
def _has_troubleshooting_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has troubleshooting signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    return any(hint in lowered for hint in _TROUBLESHOOTING_HINTS)


# Learner note: Encapsulates has operational action signal so this responsibility can be understood, tested, and changed independently.
def _has_operational_action_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has operational action signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    has_action_term = any(hint in lowered for hint in _ACTION_HINTS)
    has_action_frame = any(hint in lowered for hint in _ACTION_LEAD_HINTS)
    return has_action_term and has_action_frame


# Learner note: Encapsulates has reflection signal so this responsibility can be understood, tested, and changed independently.
def _has_reflection_signal(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing has reflection signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    if any(hint in lowered for hint in _REFLECTION_HINTS):
        return True

    has_uncertainty = any(term in lowered for term in ("not sure", "unsure", "unclear"))
    has_multiple_causes = lowered.count(" or ") >= 2
    return has_uncertainty and has_multiple_causes


# Learner note: Decides resolve auto retrieval, which controls the next branch of the application workflow.
def resolve_auto_retrieval(
    *,
    question: str,
    search_mode: str,
    enable_rerank: bool,
    enable_hyde: bool,
    enable_crag: bool,
    enable_self_reflective: bool,
) -> AutoRetrievalDecision:
    """Select retrieval mode and quality controls from deterministic query signals.

    Process:
        1. Preserve explicit non-auto settings.
        2. Detect lexical, semantic, troubleshooting, action, and ambiguity cues.
        3. Select dense, sparse, or hybrid retrieval.
        4. Add reranking, HyDE, CRAG, or self-reflection where useful.
        5. Return reasons and automatically applied flags for audit metadata.

    Why Important:
        Central policy keeps routing explainable and lets regression tests prevent
        silent quality, latency, or cost changes.
    """
    requested_search_mode = search_mode

    if search_mode != "auto":
        return AutoRetrievalDecision(
            requested_search_mode=requested_search_mode,
            resolved_search_mode=search_mode,
            enable_rerank=enable_rerank,
            enable_hyde=enable_hyde,
            enable_crag=enable_crag,
            enable_self_reflective=enable_self_reflective,
            auto_enabled=False,
            auto_strategy_reason=None,
            auto_applied_flags=[],
        )

    applied: list[str] = []
    lowered = question.lower()
    exact_token = _has_exact_token_signal(question)
    troubleshooting = _has_troubleshooting_signal(question)
    guidance = _has_guidance_signal(question)
    operational_action = _has_operational_action_signal(question)
    reflection = _has_reflection_signal(question)
    vague = _is_vague_query(question)
    semantic = _is_semantic_query(question)
    strong_conceptual = _has_strong_conceptual_signal(question)

    resolved_search_mode = "hybrid"
    reason = "balanced default retrieval for mixed operational questions"
    auto_defaults = {
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": False,
    }

    if exact_token and len(re.findall(r"[a-z0-9]+", lowered)) <= 7 and not guidance:
        resolved_search_mode = "sparse"
        reason = "short exact-token query favored sparse retrieval for lexical matching"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": False,
                "enable_crag": True,
                "enable_self_reflective": False,
            }
        )
    elif _is_direct_object_comparison(question) and not troubleshooting and not guidance:
        resolved_search_mode = "hybrid"
        reason = "direct domain-object comparison favored hybrid retrieval with reranking and no query expansion"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": False,
                "enable_crag": False,
                "enable_self_reflective": False,
            }
        )
    elif strong_conceptual and not troubleshooting and not guidance:
        resolved_search_mode = "dense"
        reason = "conceptual comparison question favored dense retrieval with HyDE and reranking"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": True,
                "enable_crag": False,
                "enable_self_reflective": False,
            }
        )
    elif reflection and (troubleshooting or operational_action):
        resolved_search_mode = "hybrid"
        reason = "ambiguous troubleshooting question favored hybrid retrieval with grounding checks and self-reflection"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": False,
                "enable_crag": True,
                "enable_self_reflective": True,
            }
        )
    elif troubleshooting or guidance or operational_action:
        resolved_search_mode = "hybrid"
        reason = "operational guidance/action query favored hybrid retrieval with grounding checks"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": False,
                "enable_crag": True,
                "enable_self_reflective": False,
            }
        )
    elif vague:
        resolved_search_mode = "dense"
        reason = "vague question favored semantic retrieval with query expansion and self-reflection"
        auto_defaults.update(
            {
                "enable_rerank": False,
                "enable_hyde": True,
                "enable_crag": True,
                "enable_self_reflective": True,
            }
        )
    elif semantic and (not exact_token or strong_conceptual):
        resolved_search_mode = "dense"
        reason = "semantic/conceptual question favored dense retrieval with HyDE and reranking"
        auto_defaults.update(
            {
                "enable_rerank": True,
                "enable_hyde": True,
                "enable_crag": False,
                "enable_self_reflective": False,
            }
        )

    resolved_enable_rerank = bool(enable_rerank or auto_defaults["enable_rerank"])
    resolved_enable_hyde = bool(enable_hyde or auto_defaults["enable_hyde"])
    resolved_enable_crag = bool(enable_crag or auto_defaults["enable_crag"])
    resolved_enable_self_reflective = bool(
        enable_self_reflective or auto_defaults["enable_self_reflective"]
    )

    if not enable_rerank and resolved_enable_rerank:
        applied.append("enable_rerank")
    if not enable_hyde and resolved_enable_hyde:
        applied.append("enable_hyde")
    if not enable_crag and resolved_enable_crag:
        applied.append("enable_crag")
    if not enable_self_reflective and resolved_enable_self_reflective:
        applied.append("enable_self_reflective")

    return AutoRetrievalDecision(
        requested_search_mode=requested_search_mode,
        resolved_search_mode=resolved_search_mode,
        enable_rerank=resolved_enable_rerank,
        enable_hyde=resolved_enable_hyde,
        enable_crag=resolved_enable_crag,
        enable_self_reflective=resolved_enable_self_reflective,
        auto_enabled=True,
        auto_strategy_reason=reason,
        auto_applied_flags=applied,
    )
