from app.config import settings


# Learner note: Computes estimate llm cost centrally so cost and confidence reporting stay consistent.
def estimate_llm_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
) -> float:
    """Perform estimate llm cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    input_cost = (prompt_tokens / 1000) * input_cost_per_1k
    output_cost = (completion_tokens / 1000) * output_cost_per_1k
    return round(input_cost + output_cost, 6)


# Learner note: Transforms format usd centrally so downstream code receives a predictable shape.
def format_usd(amount: float) -> str:
    """Perform format usd for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return f"${amount:.4f}"


# Learner note: Encapsulates answer model cost so this responsibility can be understood, tested, and changed independently.
def answer_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Perform answer model cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_answer_input_cost_per_1k,
        output_cost_per_1k=settings.llm_answer_output_cost_per_1k,
    )


# Learner note: Encapsulates grader model cost so this responsibility can be understood, tested, and changed independently.
def grader_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Perform grader model cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_grader_input_cost_per_1k,
        output_cost_per_1k=settings.llm_grader_output_cost_per_1k,
    )


# Learner note: Encapsulates sql model cost so this responsibility can be understood, tested, and changed independently.
def sql_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Perform sql model cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_sql_input_cost_per_1k,
        output_cost_per_1k=settings.llm_sql_output_cost_per_1k,
    )


# Learner note: Computes estimate sql infra cost centrally so cost and confidence reporting stay consistent.
def estimate_sql_infra_cost(*, row_count: int = 0) -> float:
    """Perform estimate sql infra cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return round(0.00008 + (min(max(row_count, 0), 50) * 0.000002), 6)


# Learner note: Computes estimate rag infra cost centrally so cost and confidence reporting stay consistent.
def estimate_rag_infra_cost(
    *,
    search_mode: str = "dense",
    top_k: int = 5,
    enable_rerank: bool = False,
    enable_hyde: bool = False,
    enable_crag: bool = False,
    enable_self_reflective: bool = False,
    used_web_fallback: bool = False,
) -> float:
    """Perform estimate rag infra cost for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    base = {
        "dense": 0.00018,
        "sparse": 0.00012,
        "hybrid": 0.00032,
    }.get(search_mode, 0.00018)
    base += min(max(top_k, 1), 20) * 0.000004
    if enable_rerank:
        base += 0.00035
    if enable_hyde:
        base += 0.00025
    if enable_crag:
        base += 0.00012
    if enable_self_reflective:
        base += 0.00015
    if used_web_fallback:
        base += 0.0002
    return round(base, 6)


# Learner note: Computes estimate infra cost saved centrally so cost and confidence reporting stay consistent.
def estimate_infra_cost_saved(
    *,
    route: str,
    cache_context: dict | None = None,
    metadata: dict | None = None,
) -> float:
    """Perform estimate infra cost saved for the observability and cost-control layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    ctx = cache_context or {}
    meta = metadata or {}
    route_name = route.lower()
    row_count = len(meta.get("sql_rows", []) or [])

    if route_name == "sql":
        return estimate_sql_infra_cost(row_count=row_count)

    rag_cost = estimate_rag_infra_cost(
        search_mode=str(ctx.get("search_mode", "dense")),
        top_k=int(ctx.get("top_k", len(meta.get("retrieved_chunks", []) or []) or 5)),
        enable_rerank=bool(ctx.get("enable_rerank", False)),
        enable_hyde=bool(ctx.get("enable_hyde", False)),
        enable_crag=bool(ctx.get("enable_crag", False)),
        enable_self_reflective=bool(ctx.get("enable_self_reflective", False)),
        used_web_fallback=bool(meta.get("used_web_fallback", False)),
    )

    if route_name == "hybrid":
        return round(rag_cost + estimate_sql_infra_cost(row_count=row_count), 6)

    if route_name == "rag":
        return rag_cost

    return 0.0
