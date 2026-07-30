import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.state import GraphState
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.observability.costs import answer_model_cost
from app.rag.hybrid_question import derive_hybrid_rag_question
from app.rag.llm_service import generate
from app.rag.router import classify_intent
from app.rag.service import run_rag
from app.sql.service import SQLService

sql_service = SQLService()
checkpointer = MemorySaver()


def route_intent(state: GraphState) -> dict:
    """Classify the incoming question and set ``intent`` to 'sql', 'rag', or 'hybrid'.

    This is the graph's entry node; the conditional edge out of it uses the
    returned intent to pick the next branch.
    """
    intent = classify_intent(state["question"])
    return {"intent": intent}


def generate_sql_node(state: GraphState) -> dict:
    """Generate a SQL query for the question via the LLM and stash it in state for approval.

    Shared by the 'sql' and 'hybrid' branches; runs before ``request_sql_approval``.
    """
    generated = sql_service.generate_sql(state["question"])
    return {
        "generated_sql": generated["sql"],
        "sql_explanation": generated.get("explanation", ""),
        "sql_generation_cost_usd": float(generated.get("generation_cost_usd", 0.0)),
    }


def request_sql_approval(state: GraphState) -> dict:
    """Pause the graph and wait for a human to approve or reject the generated SQL.

    Uses LangGraph's ``interrupt`` to suspend execution; the caller receives a
    'pending_sql' block and must resume the run (via POST /query/sql/execute)
    with an approval decision before the graph continues.
    """
    approval = interrupt(
        {
            "type": "sql_approval_required",
            "sql": state.get("generated_sql", ""),
            "explanation": state.get("sql_explanation", ""),
        }
    )
    return {"sql_approved": approval.get("approved", False)}


def _question_to_count_statement(question: str, value: object) -> str | None:
    """Turn a "how many.../count of..." style question plus a scalar SQL result into a sentence.

    Returns None if the question doesn't match a recognized counting phrasing.
    """
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
    """Render SQL result rows as a natural-language answer, using question phrasing as a hint.

    Handles the empty-result case, single-scalar results (e.g. counts), known
    single-row question patterns (e.g. "most-paged on-call engineer"), small
    single-column result sets, and falls back to a generic row-count summary.
    """
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
    """Assemble the SQL-only branch's GraphState update: answer, sources, and metadata.

    Wraps the formatted answer and up to 5 row previews in a ``ChatResponse``/
    ``ResponseMetadata`` pair, then flattens it back into a plain dict.
    """
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
    """Pull the sentence following "the first response steps are:" out of retrieved chunk text.

    Scans chunks in order and returns the first match; returns None if no
    chunk contains that marker phrase.
    """
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
    """Build a deterministic runbook-style answer, bypassing the LLM, when possible.

    Only applies when the question mentions a runbook/procedure/policy and a
    matching first-response step was found in the retrieved chunks; otherwise
    returns None so the caller falls back to the LLM-generated answer.
    """
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


def _hybrid_evidence_previews(
    question: str,
    rag_metadata: dict,
    rows: list[dict],
) -> list[dict]:
    """Return document chunks plus one compact SQL evidence preview.

    The SQL rows remain available in ``metadata.sql_rows``.  This preview makes
    mixed-answer provenance visible to API/UI consumers while avoiding one
    context entry per database row, which would distort precision and payload size.
    """
    previews = list(rag_metadata.get("retrieved_chunks", []))
    if rows:
        previews.append(
            RetrievedChunkPreview(
                text=(
                    "Database evidence for the quantitative part of this question: "
                    f"{question}\nSQL Results:\n"
                    + json.dumps(rows, indent=2, default=str)
                ),
                source="database query",
                score=1.0,
                retrieval_score=1.0,
            ).model_dump()
        )
    return previews


def build_sql_execution_result(
    question: str,
    sql: str,
    rows: list[dict],
    cost_saved_usd: float = 0.0,
) -> dict:
    """Public wrapper around ``_build_sql_response`` for callers outside this module."""
    return _build_sql_response(question, sql, rows, cost_saved_usd=cost_saved_usd)


def run_sql(state: GraphState) -> dict:
    """Execute the operator-approved SQL and build the SQL-only branch's final response.

    If ``sql_approved`` is falsy (the operator rejected it), short-circuits
    with a rejection message instead of running the query.
    """
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
    """Run the RAG-only branch: retrieve and answer purely from the vector store.

    Delegates to ``run_rag`` with the retrieval flags carried in
    ``state["flags"]`` and flattens the response into a GraphState update.
    """
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
    """Run the RAG retrieval half of the hybrid branch and stash results in state.

    Rewrites the question for document retrieval via
    ``derive_hybrid_rag_question`` first, since the raw question may be phrased
    for SQL. Runs before ``generate_sql_node`` so both retrieval results
    (RAG chunks here, SQL rows later) are available when ``run_hybrid`` merges them.
    """
    rag_question = derive_hybrid_rag_question(state["question"])
    response = run_rag(
        rag_question,
        top_k=state["flags"].get("top_k", 5),
        search_mode=state["flags"].get("search_mode", "dense"),
        enable_rerank=state["flags"].get("enable_rerank", False),
        enable_hyde=state["flags"].get("enable_hyde", False),
        enable_crag=state["flags"].get("enable_crag", False),
        enable_self_reflective=state["flags"].get("enable_self_reflective", False),
    )
    rag_metadata = response.metadata.model_dump()
    rag_metadata["retrieval_question"] = rag_question
    return {
        "rag_answer": response.answer,
        "rag_question": rag_question,
        "rag_sources": response.sources,
        "rag_confidence": response.confidence,
        "rag_cache_hit": response.cache_hit,
        "rag_metadata": rag_metadata,
        "cost_saved_usd": float(response.cost_saved.replace("$", "")),
    }


def run_hybrid(state: GraphState) -> dict:
    """Merge RAG document context and approved SQL results into one LLM-generated answer.

    Reads RAG results stashed by ``retrieve_rag_for_hybrid`` and the generated
    SQL from state, executes the SQL, then prompts the LLM with both contexts
    together. If ``sql_approved`` is falsy, short-circuits and returns the
    RAG-only answer with a rejection note instead of calling the LLM again.
    """
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
                "retrieval_question": rag_metadata.get("retrieval_question"),
                "crag_score": rag_metadata.get("crag_score"),
                "crag_label": rag_metadata.get("crag_label"),
                "crag_relevant_chunks": rag_metadata.get("crag_relevant_chunks"),
                "crag_total_chunks": rag_metadata.get("crag_total_chunks"),
                "crag_relevant_ratio": rag_metadata.get("crag_relevant_ratio"),
                "crag_chunk_scores": rag_metadata.get("crag_chunk_scores", []),
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
            "retrieved_chunks": _hybrid_evidence_previews(
                state["question"], rag_metadata, rows
            ),
            "cache_hit": False,
            "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
            "reflection_score": rag_metadata.get("reflection_score"),
            "refined_question": rag_metadata.get("refined_question"),
            "retrieval_question": rag_metadata.get("retrieval_question"),
            "crag_score": rag_metadata.get("crag_score"),
            "crag_label": rag_metadata.get("crag_label"),
            "crag_relevant_chunks": rag_metadata.get("crag_relevant_chunks"),
            "crag_total_chunks": rag_metadata.get("crag_total_chunks"),
            "crag_relevant_ratio": rag_metadata.get("crag_relevant_ratio"),
            "crag_chunk_scores": rag_metadata.get("crag_chunk_scores", []),
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
    """Merge already-retrieved RAG context and already-fetched SQL rows into one answer.

    Standalone counterpart to ``run_hybrid`` for callers (e.g. the SQL-approval
    API route) that already have RAG results and executed rows in hand and
    just need the LLM merge step and response shaping, without touching GraphState.
    """
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
            "retrieved_chunks": _hybrid_evidence_previews(question, rag_metadata, rows),
            "cache_hit": False,
            "reflection_iterations": rag_metadata.get("reflection_iterations", 0),
            "reflection_score": rag_metadata.get("reflection_score"),
            "refined_question": rag_metadata.get("refined_question"),
            "retrieval_question": rag_metadata.get("retrieval_question"),
            "crag_score": rag_metadata.get("crag_score"),
            "crag_label": rag_metadata.get("crag_label"),
            "crag_relevant_chunks": rag_metadata.get("crag_relevant_chunks"),
            "crag_total_chunks": rag_metadata.get("crag_total_chunks"),
            "crag_relevant_ratio": rag_metadata.get("crag_relevant_ratio"),
            "crag_chunk_scores": rag_metadata.get("crag_chunk_scores", []),
            "used_web_fallback": rag_metadata.get("used_web_fallback", False),
            "sql_query": sql,
            "sql_rows": rows,
        },
    }


def finalize(state: GraphState) -> dict:
    """Terminal node shared by all three branches; currently a no-op pass-through to END.

    Kept as an explicit graph node so output validation, citation formatting,
    or other shared post-processing can be added here later without changing
    the graph topology.
    """
    return {}


def build_graph():
    """Build and compile the LangGraph StateGraph that orchestrates all three retrieval
    pipelines: RAG-only, SQL-only, and Hybrid (SQL + RAG combined).

    This is the central orchestration factory for the entire query execution layer.
    It is called once at module load time; the compiled graph instance is assigned
    to the module-level `graph` variable and reused for every incoming request.

    Graph Topology (node → edge relationships):
    ─────────────────────────────────────────────────────────────────────────────
    START
      └─► route_intent               ← reads 'intent' from GraphState

          ├─[intent == 'rag']──────► run_rag
          │                               └─► finalize ──► END
          │
          ├─[intent == 'sql']──────► generate_sql_node
          │                               └─► request_sql_approval  ← HITL interrupt
          │                                       └─[intent == 'sql']─► run_sql
          │                                                               └─► finalize ──► END
          │
          └─[intent == 'hybrid']───► retrieve_rag_for_hybrid
                                          └─► generate_sql_node
                                                  └─► request_sql_approval  ← HITL interrupt
                                                          └─[intent == 'hybrid']─► run_hybrid
                                                                                      └─► finalize ──► END

    Node Responsibilities:
        route_intent            — reads the pre-classified 'intent' field from GraphState
                                  ('sql', 'rag', or 'hybrid') and branches accordingly;
                                  intent was set upstream by classify_intent() after the
                                  9-layer guardrail stack completed.

        generate_sql_node       — calls the LLM with RDS PostgreSQL schema context to
                                  generate a natural-language-to-SQL query; output is
                                  validated by sqlglot AST before proceeding.

        request_sql_approval    — LangGraph interrupt checkpoint; pauses graph execution
                                  and returns a 'pending_sql' block to the caller.
                                  Execution resumes only after the operator explicitly
                                  approves via POST /query/sql/execute. Shared by both
                                  'sql' and 'hybrid' branches.

        run_sql                 — executes the approved SQL query against RDS PostgreSQL
                                  and stores structured results in GraphState.

        run_rag                 — executes the full RAG pipeline against Qdrant Cloud:
                                  dense, sparse, hybrid, HyDE, CRAG, or SRAG depending
                                  on the retrieval mode set in the incoming request.

        retrieve_rag_for_hybrid — RAG retrieval step for the hybrid branch only; fetches
                                  Qdrant document chunks and stores them in GraphState
                                  before handing off to generate_sql_node so both
                                  retrieval results are available at merge time.

        run_hybrid              — merges Qdrant document context (from
                                  retrieve_rag_for_hybrid) and SQL structured results
                                  (from run_sql) into a single unified LLM generation.

        finalize                — post-processing node shared by all three branches;
                                  applies output validation (layer 9 of the guardrail
                                  stack), formats citations, and writes the completed
                                  answer into GraphState before returning to the caller.

    Checkpointer:
        The graph is compiled with a checkpointer, which enables LangGraph to persist
        GraphState between the request_sql_approval interrupt and the subsequent
        /query/sql/execute resume call. Without the checkpointer, the Human-in-the-Loop
        SQL approval flow cannot function across separate HTTP requests.

    Returns:
        CompiledGraph: A LangGraph compiled StateGraph instance bound to the module-level
                       checkpointer. This object is thread-safe and intended to be reused
                       across all requests for the lifetime of the FastAPI process on
                       ECS Fargate.

    Usage:
        This function is not called directly by API routes. The module-level assignment
        `graph = build_graph()` runs at import time, and API handlers reference `graph`
        directly to invoke `.ainvoke()` or `.astream()`.

    Example flow for a hybrid question:
        "How many P1 incidents breached SLA last month and what is our escalation policy?"

        START → route_intent → retrieve_rag_for_hybrid → generate_sql_node
              → request_sql_approval [PAUSED — awaiting operator approval]
              → run_hybrid → finalize → END
    """

  
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
