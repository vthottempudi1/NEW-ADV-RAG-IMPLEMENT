from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ConversationTurn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=8000)
    sources: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    search_mode: Literal["dense", "sparse", "hybrid", "auto"] = "dense"
    enable_rerank: bool = False
    enable_hyde: bool = False
    enable_crag: bool = False
    enable_self_reflective: bool = False
    conversation_context: list[ConversationTurn] = Field(default_factory=list, max_length=3)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be empty")
        return value


class RetrievedChunk(BaseModel):
    text: str
    source: str
    score: float = 0.0
    retrieval_score: float | None = None
    rerank_score: float | None = None


class RetrievedChunkPreview(BaseModel):
    text: str
    source: str
    score: float = 0.0
    retrieval_score: float | None = None
    rerank_score: float | None = None


class CRAGEvaluation(BaseModel):
    relevance_score: float = 0.0
    relevance_label: str = ""
    confidence: float = 0.0
    reasoning: str = ""


class ReflectionResult(BaseModel):
    reflection_score: float = 0.0
    needs_regeneration: bool = False
    refined_question: str = ""
    reasoning: str = ""


class ResponseMetadata(BaseModel):
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
    reflection_iterations: int = 0
    reflection_score: float | None = None
    refined_question: str | None = None
    crag_score: float | None = None
    crag_label: str | None = None
    used_web_fallback: bool = False
    sql_query: str | None = None
    sql_rows: list[dict] = Field(default_factory=list)


class PendingSQLBlock(BaseModel):
    sql: str
    query_id: str
    explanation: str = ""


class ChatResponse(BaseModel):
    answer: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pending_sql: PendingSQLBlock | None = None
    cache_hit: bool = False
    cost_saved: str = "$0.00"
    llm_cost_saved: str = "$0.00"
    infra_cost_saved: str = "$0.00"
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
