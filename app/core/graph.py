import json

from langgraph.graph import END, START, StateGraph

from app.core.state import GraphState
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.services.rag_service import run_rag
from app.services.router_service import classify_intent
from app.services.sql_service import SQLService
from app.services.llm_service import generate


sql_service = SQLService()


def route_intent(state: GraphState) -> dict:
    intent = classify_intent(state["question"])
    return {"intent": intent}


def run_sql(state: GraphState) -> dict:
    generated = sql_service.generate_sql(state["question"])
    sql = generated["sql"]
    rows = sql_service.execute_sql(sql)

    previews = [
        RetrievedChunkPreview(
            text=json.dumps(row, default=str),
            source="database query",
            score=1.0,
            retrieval_score=1.0,
        )
        for row in rows[:5]
    ]

    answer = "No results." if not rows else f"Query results:\n```json\n{json.dumps(rows, indent=2, default=str)}\n```"

    response = ChatResponse(
        answer=answer,
        sources=["database query"],
        confidence=0.9 if rows else 0.6,
        metadata=ResponseMetadata(
            route="sql",
            retrieved_chunks=previews,
        ),
    )

    return {
        "sql_rows": rows,
        "final_answer": response.answer,
        "sources": response.sources,
        "confidence": response.confidence,
        "cache_hit": response.cache_hit,
        "metadata": response.metadata.model_dump(),
    }


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
        "metadata": response.metadata.model_dump(),
    }


def run_hybrid(state: GraphState) -> dict:
    rag_response = run_rag(
        state["question"],
        top_k=state["flags"].get("top_k", 5),
        search_mode=state["flags"].get("search_mode", "dense"),
        enable_rerank=state["flags"].get("enable_rerank", False),
        enable_hyde=state["flags"].get("enable_hyde", False),
        enable_crag=state["flags"].get("enable_crag", False),
        enable_self_reflective=state["flags"].get("enable_self_reflective", False),
    )

    generated = sql_service.generate_sql(state["question"])
    sql = generated["sql"]
    rows = sql_service.execute_sql(sql)

    rag_context = "\n\n".join(
        f"[Source: {chunk.source}]\n{chunk.text}"
        for chunk in rag_response.metadata.retrieved_chunks
    )

    sql_context = json.dumps(rows, indent=2, default=str) if rows else "No SQL results."

    system = (
        "You are an enterprise assistant. "
        "Use both the retrieved document context and the SQL results to answer the question. "
        "If one side is weak, say so clearly. Stay grounded in the provided data."
    )
    user_message = (
        f"Question: {state['question']}\n\n"
        f"Document Context:\n{rag_context}\n\n"
        f"SQL Results:\n{sql_context}"
    )

    result = generate(system_prompt=system, user_message=user_message)

    sources = list(set(rag_response.sources + ["database query"]))

    return {
        "final_answer": result["text"],
        "sources": sources,
        "confidence": 0.85,
        "cache_hit": False,
        "metadata": {
            "route": "hybrid",
            "retrieved_chunks": [chunk.model_dump() for chunk in rag_response.metadata.retrieved_chunks],
            "cache_hit": False,
            "reflection_iterations": rag_response.metadata.reflection_iterations,
            "reflection_score": rag_response.metadata.reflection_score,
            "refined_question": rag_response.metadata.refined_question,
        },
    }


def finalize(state: GraphState) -> dict:
    return {}


def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("route_intent", route_intent)
    builder.add_node("run_sql", run_sql)
    builder.add_node("run_rag", run_rag_node)
    builder.add_node("run_hybrid", run_hybrid)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        lambda state: state.get("intent", "rag"),
        {
            "sql": "run_sql",
            "rag": "run_rag",
            "hybrid": "run_hybrid",
        },
    )
    builder.add_edge("run_sql", "finalize")
    builder.add_edge("run_rag", "finalize")
    builder.add_edge("run_hybrid", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


graph = build_graph()
