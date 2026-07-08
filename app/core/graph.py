import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.state import GraphState
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.services.cost_service import answer_model_cost
from app.services.rag_service import run_rag
from app.services.router_service import classify_intent
from app.services.sql_service import SQLService
from app.services.llm_service import generate


sql_service = SQLService()
checkpointer = MemorySaver()


def route_intent(state: GraphState) -> dict:
    intent = classify_intent(state["question"])
    return {"intent": intent}


def generate_sql_node(state: GraphState) -> dict:
    generated = sql_service.generate_sql(state["question"])
    return {
        "generated_sql": generated["sql"],
        "sql_explanation": generated.get("explanation", ""),
        "sql_generation_cost_usd": float(generated.get("generation_cost_usd", 0.0)),
    }


def request_sql_approval(state: GraphState) -> dict:
    approval = interrupt(
        {
            "type": "sql_approval_required",
            "sql": state.get("generated_sql", ""),
            "explanation": state.get("sql_explanation", ""),
        }
    )
    return {"sql_approved": approval.get("approved", False)}


def _question_to_count_statement(question: str, value: object) -> str | None:
    cleaned = " ".join(question.strip().split())
    lower = cleaned.lower().rstrip("?")

    if lower.startswith("how many "):
        subject = cleaned.rstrip("?")[9:].strip()
        if subject:
            return f"{value} {subject}."

    if lower.startswith("what is the count of "):
        subject = cleaned.rstrip("?")[21:].strip()
        if subject:
            return f"The count of {subject} is {value}."

    if lower.startswith("count "):
        subject = cleaned.rstrip("?")[6:].strip()
        if subject:
            return f"The count of {subject} is {value}."

    return None


def _format_sql_answer(question: str, rows: list[dict]) -> str:
    cleaned = " ".join(question.strip().split())
    lowered = cleaned.lower().rstrip("?")

    if not rows:
        if lowered.startswith("show me details for cluster "):
            cluster_ref = cleaned.rstrip("?")[len("Show me details for cluster ") :]
            return f"No exact cluster matched '{cluster_ref}'."
        return "No matching records were found."

    if len(rows) == 1:
        row = rows[0]
        if len(row) == 1:
            value = next(iter(row.values()))
            count_statement = _question_to_count_statement(question, value)
            if count_statement:
                return count_statement
            return f"The result is {value}."

        if lowered == "which on-call engineer has been paged the most times this month":
            engineer = row.get("engineer")
            page_count = row.get("page_count")
            if engineer is not None and page_count is not None:
                return (
                    f"The on-call engineer paged the most times this month is "
                    f"{engineer} with {page_count} pages."
                )

        if lowered.startswith("show me details for cluster "):
            parts = [f"{key}={value}" for key, value in row.items()]
            cluster_ref = cleaned.rstrip("?")[len("Show me details for cluster ") :]
            return f"Cluster details for '{cluster_ref}': " + ", ".join(parts) + "."

        parts = [f"{key}={value}" for key, value in row.items()]
        return "The query returned one row: " + ", ".join(parts) + "."

    if len(rows) <= 5 and all(len(row) == 1 for row in rows):
        lines = []
        for row in rows:
            key, value = next(iter(row.items()))
            lines.append(f"- {key}: {value}")
        return "The query returned the following results:\n" + "\n".join(lines)

    return f"The query returned {len(rows)} rows."


def _build_sql_response(
    question: str,
    sql: str,
    rows: list[dict],
    cost_saved_usd: float = 0.0,
) -> dict:
    answer = _format_sql_answer(question, rows)
    previews = [
        RetrievedChunkPreview(
            text=answer if index == 0 else json.dumps(row, default=str),
            source="database query",
            score=1.0,
            retrieval_score=1.0,
        )
        for index, row in enumerate(rows[:5])
    ]

    response = ChatResponse(
        answer=answer,
        sources=["database query"],
        confidence=0.9 if rows else 0.6,
        metadata=ResponseMetadata(
            route="sql",
            retrieved_chunks=previews,
            sql_query=sql,
            sql_rows=rows,
        ),
    )

    return {
        "sql_rows": rows,
        "final_answer": response.answer,
        "sources": response.sources,
        "confidence": response.confidence,
        "cache_hit": response.cache_hit,
        "cost_saved_usd": round(float(cost_saved_usd), 6),
        "metadata": response.metadata.model_dump(),
    }


def _extract_runbook_first_steps(retrieved_chunks: list[dict]) -> str | None:
    for chunk in retrieved_chunks:
        text = chunk.get("text", "")
        if not isinstance(text, str):
            continue
        lowered = text.lower()
        marker = "the first response steps are:"
        index = lowered.find(marker)
        if index < 0:
            continue
        snippet = text[index + len(marker):].strip()
        sentence = snippet.split(".")[0].strip(" \n\r\t;:")
        if sentence:
            return sentence
    return None


def _build_operational_hybrid_answer(
    *,
    question: str,
    rows: list[dict],
    rag_metadata: dict,
) -> str | None:
    lowered = question.lower()
    if "runbook" not in lowered and "procedure" not in lowered and "policy" not in lowered:
        return None

    first_steps = _extract_runbook_first_steps(rag_metadata.get("retrieved_chunks", []))
    if not first_steps:
        return None

    sql_answer = _format_sql_answer(question, rows)
    return (
        f"{sql_answer}\n\n"
        "The documented first response steps are to "
        f"{first_steps}."
    )


def build_sql_execution_result(
    question: str,
    sql: str,
    rows: list[dict],
    cost_saved_usd: float = 0.0,
) -> dict:
    return _build_sql_response(question, sql, rows, cost_saved_usd=cost_saved_usd)


def run_sql(state: GraphState) -> dict:
    if not state.get("sql_approved"):
        return {
            "sql_rows": [],
            "final_answer": "SQL query was not approved.",
            "sources": [],
            "confidence": 0.0,
            "cache_hit": False,
            "metadata": {"route": "sql", "retrieved_chunks": []},
        }

    sql = state.get("generated_sql", "")
    rows = sql_service.execute_sql(sql)
    return _build_sql_response(
        state["question"],
        sql,
        rows,
        cost_saved_usd=float(state.get("sql_generation_cost_usd", 0.0)),
    )


def run_rag_node(state: GraphState) -> dict:
    response = run_rag(
        state["question"],
        top_k=state["flags"].get("top_k", 5),
        search_mode=state["flags"].get("search_mode", "dense"),
        enable_rerank=state["flags"].get("enable_rerank", False),
        enable_hyde=state["flags"].get("enable_hyde", False),
        enable_crag=state["flags"].get("enable_crag", False),
        enable_self_reflective=state["flags"].get("enable_self_reflective", False),
    )
    return {
        "final_answer": response.answer,
        "sources": response.sources,
        "confidence": response.confidence,
        "cache_hit": response.cache_hit,
        "cost_saved_usd": float(response.cost_saved.replace("$", "")),
        "metadata": response.metadata.model_dump(),
    }


def retrieve_rag_for_hybrid(state: GraphState) -> dict:
    response = run_rag(
        state["question"],
        top_k=state["flags"].get("top_k", 5),
        search_mode=state["flags"].get("search_mode", "dense"),
        enable_rerank=state["flags"].get("enable_rerank", False),
        enable_hyde=state["flags"].get("enable_hyde", False),
        enable_crag=state["flags"].get("enable_crag", False),
        enable_self_reflective=state["flags"].get("enable_self_reflective", False),
    )
    return {
        "rag_answer": response.answer,
        "rag_sources": response.sources,
        "rag_confidence": response.confidence,
        "rag_cache_hit": response.cache_hit,
        "rag_metadata": response.metadata.model_dump(),
        "cost_saved_usd": float(response.cost_saved.replace("$", "")),
    }


def run_hybrid(state: GraphState) -> dict:
    if not state.get("sql_approved"):
        rag_metadata = state.get("rag_metadata", {})
        return {
            "sql_rows": [],
            "final_answer": "SQL query was not approved.",
            "sources": state.get("rag_sources", []),
            "confidence": state.get("rag_confidence", 0.0),
            "cache_hit": False,
            "cost_saved_usd": float(state.get("cost_saved_usd", 0.0)),
            "metadata": {
                "route": "hybrid",
                "retrieved_chunks": rag_metadata.get("retrieved_chunks", []),
                "cache_hit": False,
                "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
                "reflection_score": rag_metadata.get("reflection_score"),
                "refined_question": rag_metadata.get("refined_question"),
                "crag_score": rag_metadata.get("crag_score"),
                "crag_label": rag_metadata.get("crag_label"),
                "used_web_fallback": rag_metadata.get("used_web_fallback", False),
                "sql_query": state.get("generated_sql", ""),
                "sql_rows": [],
            },
        }

    sql = state.get("generated_sql", "")
    rows = sql_service.execute_sql(sql)
    rag_metadata = state.get("rag_metadata", {})
    rag_context = "\n\n".join(
        f"[Source: {chunk['source']}]\n{chunk['text']}"
        for chunk in rag_metadata.get("retrieved_chunks", [])
    )

    sql_context = json.dumps(rows, indent=2, default=str) if rows else "No SQL results."
    sql_summary = _format_sql_answer(state["question"], rows)

    system = (
        "You are an enterprise assistant. "
        "Use both the retrieved document context and the SQL results to answer the question. "
        "If one side is weak, say so clearly. Stay grounded in the provided data. "
        "If the document context contains a runbook, policy, or procedure with first-response steps, "
        "extract and present those steps even if the severity label is not an exact match, as long as "
        "the guidance is clearly the closest relevant documented procedure. "
        "Do not claim the runbook lacks guidance when first-step instructions are present."
    )
    user_message = (
        f"Question: {state['question']}\n\n"
        f"Document Context:\n{rag_context}\n\n"
        f"SQL Summary:\n{sql_summary}\n\n"
        f"SQL Results:\n{sql_context}"
    )

    result = generate(system_prompt=system, user_message=user_message)
    usage = result.get("usage", {})
    hybrid_answer_cost_usd = answer_model_cost(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )
    final_answer = _build_operational_hybrid_answer(
        question=state["question"],
        rows=rows,
        rag_metadata=rag_metadata,
    ) or result["text"]

    sources = list(set(state.get("rag_sources", []) + ["database query"]))

    return {
        "sql_rows": rows,
        "final_answer": final_answer,
        "sources": sources,
        "confidence": 0.85,
        "cache_hit": False,
        "cost_saved_usd": round(
            float(state.get("cost_saved_usd", 0.0))
            + float(state.get("sql_generation_cost_usd", 0.0))
            + hybrid_answer_cost_usd,
            6,
        ),
        "metadata": {
            "route": "hybrid",
            "retrieved_chunks": rag_metadata.get("retrieved_chunks", []),
            "cache_hit": False,
            "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
            "reflection_score": rag_metadata.get("reflection_score"),
            "refined_question": rag_metadata.get("refined_question"),
            "crag_score": rag_metadata.get("crag_score"),
            "crag_label": rag_metadata.get("crag_label"),
            "used_web_fallback": rag_metadata.get("used_web_fallback", False),
            "sql_query": sql,
            "sql_rows": rows,
        },
    }


def build_hybrid_execution_result(
    *,
    question: str,
    sql: str,
    rows: list[dict],
    rag_sources: list[str],
    rag_confidence: float,
    rag_metadata: dict,
    cost_saved_usd: float = 0.0,
) -> dict:
    rag_context = "\n\n".join(
        f"[Source: {chunk['source']}]\n{chunk['text']}"
        for chunk in rag_metadata.get("retrieved_chunks", [])
    )
    sql_context = json.dumps(rows, indent=2, default=str) if rows else "No SQL results."
    sql_summary = _format_sql_answer(question, rows)
    system = (
        "You are an enterprise assistant. "
        "Use both the retrieved document context and the SQL results to answer the question. "
        "If one side is weak, say so clearly. Stay grounded in the provided data. "
        "If the document context contains a runbook, policy, or procedure with first-response steps, "
        "extract and present those steps even if the severity label is not an exact match, as long as "
        "the guidance is clearly the closest relevant documented procedure. "
        "Do not claim the runbook lacks guidance when first-step instructions are present."
    )
    user_message = (
        f"Question: {question}\n\n"
        f"Document Context:\n{rag_context}\n\n"
        f"SQL Summary:\n{sql_summary}\n\n"
        f"SQL Results:\n{sql_context}"
    )
    result = generate(system_prompt=system, user_message=user_message)
    usage = result.get("usage", {})
    hybrid_answer_cost_usd = answer_model_cost(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )
    final_answer = _build_operational_hybrid_answer(
        question=question,
        rows=rows,
        rag_metadata=rag_metadata,
    ) or result["text"]
    return {
        "sql_rows": rows,
        "final_answer": final_answer,
        "sources": list(set((rag_sources or []) + ["database query"])),
        "confidence": max(0.85, rag_confidence or 0.0),
        "cache_hit": False,
        "cost_saved_usd": round(float(cost_saved_usd) + hybrid_answer_cost_usd, 6),
        "metadata": {
            "route": "hybrid",
            "retrieved_chunks": rag_metadata.get("retrieved_chunks", []),
            "cache_hit": False,
            "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
            "reflection_score": rag_metadata.get("reflection_score"),
            "refined_question": rag_metadata.get("refined_question"),
            "crag_score": rag_metadata.get("crag_score"),
            "crag_label": rag_metadata.get("crag_label"),
            "used_web_fallback": rag_metadata.get("used_web_fallback", False),
            "sql_query": sql,
            "sql_rows": rows,
        },
    }


def finalize(state: GraphState) -> dict:
    return {}


def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("route_intent", route_intent)
    builder.add_node("generate_sql_node", generate_sql_node)
    builder.add_node("request_sql_approval", request_sql_approval)
    builder.add_node("run_sql", run_sql)
    builder.add_node("run_rag", run_rag_node)
    builder.add_node("retrieve_rag_for_hybrid", retrieve_rag_for_hybrid)
    builder.add_node("run_hybrid", run_hybrid)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        lambda state: state.get("intent", "rag"),
        {
            "sql": "generate_sql_node",
            "rag": "run_rag",
            "hybrid": "retrieve_rag_for_hybrid",
        },
    )
    builder.add_edge("generate_sql_node", "request_sql_approval")
    builder.add_conditional_edges(
        "request_sql_approval",
        lambda state: state.get("intent", "sql"),
        {
            "sql": "run_sql",
            "hybrid": "run_hybrid",
        },
    )
    builder.add_edge("run_sql", "finalize")
    builder.add_edge("run_rag", "finalize")
    builder.add_edge("retrieve_rag_for_hybrid", "generate_sql_node")
    builder.add_edge("run_hybrid", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
