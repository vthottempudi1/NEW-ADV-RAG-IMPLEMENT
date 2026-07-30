from app.config import settings


def estimate_llm_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
) -> float:
    """Compute the dollar cost of an LLM call from token counts and per-1k rates.

    Prompt and completion tokens are priced independently and the total is
    rounded to 6 decimal places to avoid floating-point noise in reported costs.
    """
    input_cost = (prompt_tokens / 1000) * input_cost_per_1k
    output_cost = (completion_tokens / 1000) * output_cost_per_1k
    return round(input_cost + output_cost, 6)


def format_usd(amount: float) -> str:
    """Format a dollar amount as a USD string with 4 decimal places (e.g. "$0.0012")."""
    return f"${amount:.4f}"


def answer_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the cost of an answer-generation LLM call using configured answer-model rates."""
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_answer_input_cost_per_1k,
        output_cost_per_1k=settings.llm_answer_output_cost_per_1k,
    )


def grader_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the cost of a grading/evaluation LLM call using configured grader-model rates."""
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_grader_input_cost_per_1k,
        output_cost_per_1k=settings.llm_grader_output_cost_per_1k,
    )


def sql_model_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the cost of a text-to-SQL generation LLM call using configured SQL-model rates."""
    return estimate_llm_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost_per_1k=settings.llm_sql_input_cost_per_1k,
        output_cost_per_1k=settings.llm_sql_output_cost_per_1k,
    )


def estimate_sql_infra_cost(*, row_count: int = 0) -> float:
    """Estimate the non-LLM infrastructure cost of executing a SQL query.

    Uses a fixed base cost plus a small per-row surcharge, with row_count
    clamped to the [0, 50] range so unusually large result sets don't skew
    the estimate.
    """
    return round(0.00008 + (min(max(row_count, 0), 50) * 0.000002), 6)


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
    """Estimate the non-LLM infrastructure cost of a RAG retrieval pipeline run.

    Starts from a base cost keyed by search_mode ("dense", "sparse", or
    "hybrid", defaulting to the dense rate for unknown modes), adds a
    per-result surcharge for top_k (clamped to [1, 20]), and adds flat
    surcharges for each optional pipeline stage that was enabled (reranking,
    HyDE, CRAG, self-reflection, and web-search fallback).
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


def estimate_infra_cost_saved(
    *,
    route: str,
    cache_context: dict | None = None,
    metadata: dict | None = None,
) -> float:
    """Estimate the infrastructure cost avoided by serving a request from cache instead of running it live.

    Dispatches on route ("sql", "rag", "hybrid", or anything else) to combine
    estimate_sql_infra_cost and/or estimate_rag_infra_cost using details pulled
    from cache_context (search settings) and metadata (result counts, web
    fallback usage). Returns 0.0 for unrecognized routes.
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
