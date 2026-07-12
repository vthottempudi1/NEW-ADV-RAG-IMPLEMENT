from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Learner Note: Conversation turn is part of the enterprise RAG application.
class ConversationTurn(BaseModel):
    """A validated prior exchange used to resolve multi-turn questions."""
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=8000)
    sources: list[str] = Field(default_factory=list)


# Learner Note: Query request is part of the enterprise RAG application.
class QueryRequest(BaseModel):
    """The validated API contract controlling one enterprise RAG request.

    Architecture Role:
        Defines the trust boundary between clients and routing, retrieval,
        reranking, generation, CRAG, HyDE, and self-reflection services.
    Process:
        Validates the question, retrieval depth, search mode, advanced-RAG flags,
        and a bounded conversation history before workflow execution.
    Why Important:
        Early validation prevents malformed input, unbounded retrieval, avoidable
        model cost, and inconsistent downstream behavior.
    """
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    search_mode: Literal["dense", "sparse", "hybrid", "auto"] = "dense"
    enable_rerank: bool = False
    enable_hyde: bool = False
    enable_crag: bool = False
    enable_self_reflective: bool = False
    conversation_context: list[ConversationTurn] = Field(default_factory=list, max_length=3)

    # Learner note: Evaluates validate question as a guardrail before later pipeline stages proceed.
    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """Trim the question and reject whitespace-only input before retrieval."""
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be empty")
        return value


# Learner Note: Retrieved chunk is part of the enterprise RAG application.
class RetrievedChunk(BaseModel):
    """A complete evidence chunk with retrieval and optional reranker scores."""
    text: str
    source: str
    metadata: dict = Field(default_factory=dict)
    score: float = 0.0
    retrieval_score: float | None = None
    rerank_score: float | None = None


# Learner Note: Retrieved chunk preview is part of the enterprise RAG application.
class RetrievedChunkPreview(BaseModel):
    """API-safe evidence metadata exposed for source and score inspection."""
    text: str
    source: str
    score: float = 0.0
    retrieval_score: float | None = None
    rerank_score: float | None = None


# Learner Note: Chunk relevance preserves CRAG's evidence-level judgment for auditing.
class ChunkRelevance(BaseModel):
    """Record one chunk's relevance score and explanation."""

    index: int
    source: str
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance_label: str = "irrelevant"
    reasoning: str = ""


# Learner Note: C r a g evaluation is part of the enterprise RAG application.
class CRAGEvaluation(BaseModel):
    """CRAG's structured judgment of context relevance and confidence."""
    relevance_score: float = 0.0
    relevance_label: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    chunk_evaluations: list[ChunkRelevance] = Field(default_factory=list)
    relevant_chunk_count: int = 0
    total_chunk_count: int = 0
    relevant_ratio: float = 0.0


# Learner Note: Reflection result is part of the enterprise RAG application.
class ReflectionResult(BaseModel):
    """Self-RAG's decision about answer quality and possible regeneration."""
    reflection_score: float = 0.0
    needs_regeneration: bool = False
    refined_question: str = ""
    reasoning: str = ""


# Learner Note: Response metadata is part of the enterprise RAG application.
class ResponseMetadata(BaseModel):
    """Auditable routing, evidence, SQL, CRAG, and reflection metadata.

    Why Important:
        Operators can inspect source provenance and execution decisions without
        parsing answer prose or relying on hidden application state.
    """
    route: str = "rag"
    retrieved_chunks: list[RetrievedChunkPreview] = Field(default_factory=list)
    cache_hit: bool = False
    requested_search_mode: str | None = None
    resolved_search_mode: str | None = None
    resolved_enable_rerank: bool | None = None
    resolved_enable_hyde: bool | None = None
    resolved_enable_crag: bool | None = None
    resolved_enable_self_reflective: bool | None = None
    auto_enabled: bool = False
    auto_strategy_reason: str | None = None
    auto_applied_flags: list[str] = Field(default_factory=list)
    original_question: str | None = None
    resolved_question: str | None = None
    resolved_follow_up_subject: str | None = None
    retrieval_question: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_reason: str | None = None
    clarification_type: str | None = None
    reflection_iterations: int = 0
    reflection_score: float | None = None
    refined_question: str | None = None
    crag_score: float | None = None
    crag_label: str | None = None
    crag_relevant_chunks: int | None = None
    crag_total_chunks: int | None = None
    crag_relevant_ratio: float | None = None
    crag_chunk_scores: list[dict] = Field(default_factory=list)
    used_web_fallback: bool = False
    sql_query: str | None = None
    sql_rows: list[dict] = Field(default_factory=list)


# Learner Note: Pending s q l block is part of the enterprise RAG application.
class PendingSQLBlock(BaseModel):
    """A generated read-only SQL statement awaiting explicit approval."""
    sql: str
    query_id: str
    explanation: str = ""


# Learner Note: Chat response is part of the enterprise RAG application.
class ChatResponse(BaseModel):
    """Stable response envelope shared by API, cache, eval, and frontend."""
    answer: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pending_sql: PendingSQLBlock | None = None
    cache_hit: bool = False
    cost_saved: str = "$0.00"
    llm_cost_saved: str = "$0.00"
    infra_cost_saved: str = "$0.00"
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
