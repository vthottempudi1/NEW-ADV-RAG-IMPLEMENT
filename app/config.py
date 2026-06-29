from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    llm_model_answer: str = "gpt-4o"
    llm_model_grader: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    qdrant_url: str = "http://localhost:6334"
    qdrant_collection: str = "new_adv_rag_documents"

    database_url: str = "postgresql://postgres:postgres@localhost:5434/adv_rag"

    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    jwt_secret: str = "change-me"
    jwt_expiration_minutes: int = 60

    tavily_api_key: str = ""

    storage_backend: str = "local"
    s3_cache_bucket: str = ""
    aws_region: str = "us-east-1"

    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_tokens_per_user_daily: int = 100000
    max_input_tokens: int = 3000
    reserved_output_tokens: int = 1000

    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_initial_top_k: int = 20
    reranking_enabled_by_default: bool = True

    hyde_num_hypotheses: int = 3
    hyde_enabled_by_default: bool = False

    crag_relevance_threshold: float = 0.7
    crag_ambiguous_threshold: float = 0.5

    reflection_min_score: float = 0.85
    max_reflection_retries: int = 2
    self_reflective_enabled_by_default: bool = False


settings = Settings()