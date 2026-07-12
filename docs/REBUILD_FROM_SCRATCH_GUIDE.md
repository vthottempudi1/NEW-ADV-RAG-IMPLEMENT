# Enterprise Advanced RAG Rebuild From Scratch Guide

> Evaluation case study: the detailed evidence behind the retrieval, evaluator,
> chunking, and ingestion design decisions is recorded in
> [`EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md`](EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md).
> This rebuild guide describes the target construction process; the case study
> describes the bugs and experiments that produced those requirements.

This guide is the clean reconstruction order for rebuilding the project from nothing and then carrying it all the way through deployment and validation.

Use it when you want:

- a clean reimplementation sequence
- a dependency-aware development order
- a repeatable path from local backend to AWS deployment
- a checklist for testing, observability, and evidence capture

For the current live implementation details, also read:

- `new-adv-rag-implement/WRITEUP.md`
- `new-adv-rag-implement/AWS_DEPLOYMENT.md`

## 1. Rebuild Goal

The goal is not only to recreate features. The goal is to rebuild the system in the right order so you do not get blocked by:

- missing lower-level modules
- scattered ingestion logic
- unsafe SQL shortcuts
- cache bugs
- deployment-only failures
- missing validation evidence

The correct target is a system that is:

- explainable
- testable
- deployable
- observable
- demo-ready

## 2. Final Target Scope

By the end of the rebuild, the system should support:

- document upload and dedupe
- chunking and embeddings
- vector indexing in Qdrant
- dense, sparse, and hybrid retrieval
- reranking, HyDE, CRAG, and self-reflective RAG controls
- SQL routing with `sqlglot`-based safety
- hybrid SQL + RAG answers
- human approval for SQL execution
- JWT auth and admin protection
- rate limits and token budgets
- query and embedding caching
- admin observability endpoints
- CI-safe evaluation
- AWS deployment with HTTPS
- CloudWatch dashboard and load-test evidence

## 3. Build Order Overview

Build in this order:

1. project foundation
2. configuration and shared models
3. storage and cache primitives
4. ingestion pipeline
5. vector and retrieval services
6. LLM, RAG, SQL, and routing services
7. security and middleware
8. orchestration graph
9. API routes
10. scripts and admin tooling
11. tests and evaluation
12. containerization and cloud deployment
13. monitoring and load validation

Do not start with `rag_service.py`.

## 4. Phase 1: Foundation

Create the project scaffold first:

- `pyproject.toml`
- `.env.example`
- `Dockerfile`
- `infra/docker/streamlit.Dockerfile`
- `docker-compose.yml`
- `app/main.py`
- `app/config.py`
- `app/models.py`
- `ui/streamlit/app.py`

Foundation requirements:

- FastAPI app boots locally
- Streamlit app boots locally
- config comes from environment variables
- local Docker services for PostgreSQL and Qdrant work

Recommended local-first flow:

1. create venv
2. install dev dependencies
3. start Docker infra
4. confirm backend `/health`
5. confirm Streamlit boot

## 5. Phase 2: Configuration And Shared Contracts

Define `Settings` cleanly in `app/config.py`.

Required config groups:

- LLM model config
- embedding model config
- PostgreSQL config
- Qdrant config
- Redis / Upstash config
- S3 / storage config
- JWT config
- rate limits
- token budgets
- retrieval defaults
- observability / logging toggles

Define shared contracts in `app/models.py`:

- `QueryRequest`
- `ChatResponse`
- `PendingSQLBlock`
- `ResponseMetadata`
- `RetrievedChunk`
- `RetrievedChunkPreview`
- `CRAGEvaluation`
- `ReflectionResult`

Define graph state in `app/core/state.py`.

Do this early so the rest of the system is not built around ad hoc dictionaries.

## 6. Phase 3: Storage And Cache Primitives

Create:

- `app/storage/storage_backend.py`
- `app/storage/local_storage.py`
- `app/storage/s3_storage.py`
- `app/caching/query_cache.py`
- `app/services/doc_cache_service.py`

Rules:

- `QueryCacheService` handles query-time cache
- `DocCacheService` handles ingestion dedupe and document metadata
- keep these responsibilities separate

Cache tiers to support:

- intent
- rag answer
- SQL generation
- SQL result
- embeddings

Storage backends to support:

- local filesystem
- S3

## 7. Phase 4: Ingestion Pipeline

Create:

- `app/services/document_processor.py`
- `app/services/embedding_service.py`
- `app/rag/vector_store.py`
- `app/ingestion/service.py`

Required ingestion flow:

1. accept bytes or file path
2. compute content hash
3. short-circuit duplicates
4. parse document
5. chunk text
6. embed chunks
7. upsert vectors
8. store original file through storage backend
9. persist ingestion metadata

Important lessons from this project:

- chunking belongs in the app, not in Qdrant
- original document metadata should stay attached for traceability
- chunk identity should be deterministic
- dedupe should be content-based, not filename-based

Metadata to persist:

- `content_hash`
- `filename`
- `storage_backend`
- `storage_key`
- `storage_url`
- `chunks_indexed`
- `indexed_at`

## 8. Phase 5: Retrieval And Search Services

Create:

- `app/rag/router.py`
- `app/services/reranking.py`
- `app/rag/hyde.py`
- `app/rag/crag.py`
- `app/rag/self_reflective.py`
- `app/services/web_search.py`

Implement retrieval modes in `vector_store.py` and `rag_service.py`:

- dense
- sparse
- hybrid

Then add:

- reranking
- HyDE
- CRAG
- self-reflection

Practical guidance:

- make hybrid the default candidate
- keep the advanced features optional until evals prove they help
- do not blindly trust reranking on noisy corpora

## 9. Phase 6: LLM, RAG, SQL, And Auto Retrieval

Create:

- `app/services/llm_service.py`
- `app/rag/service.py`
- `app/sql/service.py`
- `app/rag/auto_retrieval.py`
- `app/services/system_prompt.py`

### RAG Service Responsibilities

- retrieve chunks
- optionally rerank
- optionally run HyDE / CRAG / reflection
- build spotlighted context
- generate answer
- cache answer
- return response metadata

### SQL Service Responsibilities

- introspect schema
- generate SQL
- validate SQL via `sqlglot`
- execute only safe read-only queries
- cache generated SQL and SQL results

### Auto Retrieval Responsibilities

- map `search_mode="auto"` to an actual strategy
- record:
  - `requested_search_mode`
  - `resolved_search_mode`
  - `auto_strategy_reason`

This is a meaningful production feature because it moves retrieval choice into backend policy.

## 10. Phase 7: Security And Middleware

Create:

- `app/middleware/auth.py`
- `app/middleware/rate_limiter.py`
- `app/security/input_guard.py`
- `app/security/input_restructuring.py`
- `app/security/content_moderation.py`
- `app/security/output_validator.py`
- `app/security/token_budget.py`
- `app/security/spotlighting.py`

Minimum guardrail path for `/query`:

1. auth
2. rate limit
3. token budget
4. input restructuring
5. input safety
6. moderation / redaction
7. graph execution
8. output validation

## 11. Phase 8: Orchestration Graph

Create:

- `app/core/graph.py`

Graph must support:

- `rag`
- `sql`
- `hybrid`

Required behavior:

- SQL route can return `pending_sql`
- hybrid route can retrieve document context and pause for SQL approval
- final answer merges SQL and RAG outputs when needed

## 12. Phase 9: API Routes

Create:

- `app/api/auth.py`
- `app/api/v1/query.py`
- `app/api/admin.py`
- `app/api/documents.py`

Required endpoints:

- `POST /auth/register`
- `POST /auth/login`
- `POST /query`
- `POST /query/sql/execute`
- `POST /documents/upload`
- admin health / runtime / cache endpoints

Important design rule:

- `/documents/upload` should call `IngestionService`
- do not put ingestion orchestration directly in the route

## 13. Phase 10: Scripts, Seeders, And Local Tooling

Create:

- `scripts/seed_db.py`
- optional reindex / cache-clear scripts

Script rules:

- scripts should call services
- scripts should not duplicate service logic
- seeding should be deterministic where possible

Use scripts to:

- create demo users
- seed SQL tables
- ingest seed documents

## 14. Phase 11: Tests And Evaluation

Create tests for:

- auth
- query cache
- ingestion dedupe
- SQL validation
- vector-store behavior
- RAG service
- API auth / query
- hybrid routing
- admin routes
- eval smoke path

Minimum test goals:

- `/query` requires auth
- duplicate upload is skipped
- unsafe SQL is rejected
- response metadata is stable
- cache-hit behavior is correct
- approval flow behaves as expected

Evaluation goals:

- fixture-safe CI smoke evals
- local profile-based eval runs
- compare retrieval strategies against clean and noisy corpora

## 15. Phase 12: Local End-To-End Validation

Before any AWS work, validate locally:

1. register / login
2. upload a document
3. ask a pure RAG question
4. ask a SQL question
5. ask a hybrid question
6. approve SQL execution
7. repeat the same question and confirm cache behavior

Local validation should confirm:

- functionality
- metadata correctness
- cache correctness
- source traceability

## 16. Phase 13: Containerization And Packaging

Build two images:

- backend
- streamlit

Packaging lessons from this project:

- separate runtime requirements from source copy for faster rebuilds
- keep `.dockerignore` aggressive
- avoid building from the wrong parent workspace
- verify Streamlit image content if the deployed UI looks older than local code

Required Docker hardening:

- UTF-8 environment variables for container runtime
- safe stdout/stderr encoding in backend startup

## 17. Phase 14: AWS Deployment

Follow this order:

1. configure AWS CLI
2. create ECR repos
3. build and push images
4. create RDS
5. create S3 bucket
6. prepare Qdrant Cloud
7. create Secrets Manager secret
8. create ECS cluster
9. create IAM roles
10. create CloudWatch log groups
11. register task definitions
12. create target groups
13. create ALBs
14. create ECS services
15. add ACM + Route 53 + HTTPS
16. validate backend and frontend

For the exact resource names and current live values, see `new-adv-rag-implement/AWS_DEPLOYMENT.md`.

## 18. Phase 15: Production Validation

After AWS deployment, validate:

- backend health
- frontend reachability
- auth flow
- upload flow
- RAG query
- SQL query + approval
- hybrid query + approval
- Auto mode metadata
- cache-hit behavior

Then add:

- CloudWatch alarms
- ECS autoscaling
- CloudWatch dashboard

## 19. Phase 16: Load Testing And Evidence

Run in this order:

1. `health.js`
2. `query_rag.js`
3. `mixed_smoke.js`

Recommended commands:

```powershell
cd C:\Users\vthot\PORTFOLIO-PROJECTS\ENTERPRISE-ADV-RAG\new-adv-rag-implement
.\loadtests\run_k6.ps1 -Script "health.js" -Duration "30s" -Vus "2"
.\loadtests\run_k6.ps1 -Script "query_rag.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -Vus "2"
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -RagVus "1" -SqlVus "1" -HybridVus "1"
```

Dashboard evidence workflow:

1. open CloudWatch dashboard `new-adv-rag-ops`
2. enable auto-refresh at `10s`
3. capture one screenshot during the run
4. capture a clean post-run screenshot with a custom time range
5. capture ECS backend health if needed
6. save raw `k6` output and markdown summary

## 20. Recommended Documentation Set

After the rebuild is complete, maintain:

- `WRITEUP.md`
- `AWS_DEPLOYMENT.md`
- `REBUILD_FROM_SCRATCH_GUIDE.md`
- a final load-test summary under `loadtests/results/`

This keeps:

- architecture narrative
- operational runbook
- rebuild sequence
- validation evidence

separate and readable.

## 21. Common Mistakes To Avoid

- starting with high-level RAG logic before lower-level services exist
- mixing document dedupe with query cache logic
- scattering ingestion logic across routes and scripts
- using only regex SQL guards
- assuming healthy containers imply healthy ALB targets
- forgetting RDS SG ingress from ECS
- leaving Streamlit pointed at localhost
- assuming CloudWatch auto-created scaling alarms are the same as manual alarms
- treating one successful local run as enough validation

## 22. Best Practical Rebuild Path

If rebuilding again from zero, the safest sequence is:

1. foundation
2. config + models
3. storage + cache
4. ingestion
5. retrieval
6. RAG path
7. SQL path
8. hybrid path
9. security
10. admin routes
11. tests
12. AWS deployment
13. CloudWatch dashboard
14. load testing
15. final documentation

That ordering prevents advanced behavior from being built on unstable ingestion or deployment assumptions.

## 23. Bottom Line

The right rebuild is not just about recreating features. It is about reaching a final state where development, deployment, validation, monitoring, and evidence capture all happen in a repeatable sequence.
