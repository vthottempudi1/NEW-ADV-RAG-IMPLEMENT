from operator import add
from typing import Annotated, TypedDict

from app.models import CRAGEvaluation, ReflectionResult, RetrievedChunk


class GraphState(TypedDict, total=False):
    question: str
    user_id: str
    flags: dict

    intent: str
    generated_sql: str
    sql_explanation: str
    sql_generation_cost_usd: float
    sql_approved: bool
    sql_rows: list[dict]
    sql_cache_hit: bool

    hypotheses: list[str]

    retrieved_chunks: Annotated[list[RetrievedChunk], add]
    reranked_chunks: list[RetrievedChunk]
    spotlighted_context: str

    crag_evaluation: CRAGEvaluation
    web_results: list[RetrievedChunk]

    rag_cache_hit: bool
    raw_answer: str
    rag_answer: str
    rag_sources: list[str]
    rag_confidence: float
    rag_metadata: dict

    reflection: ReflectionResult
    reflection_iterations: int
    refined_question: str

    final_answer: str
    sources: list[str]
    confidence: float

    chunk_previews: list[dict]
    cache_hits: dict[str, bool]
    cost_saved_usd: float
    cache_hit: bool
    metadata: dict
