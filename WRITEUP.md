# New Advanced RAG Implement Writeup

## 1. Executive Summary

`new-adv-rag-implement` is a production-minded enterprise RAG backend and Streamlit frontend built to demonstrate more than a basic retrieval chatbot.

The project supports:

- document upload with duplicate-safe ingestion
- dense, sparse, and hybrid retrieval
- backend-owned `search_mode="auto"` resolution
- reranking, HyDE, CRAG, and self-reflective RAG controls
- SQL routing with AST-based SQL safety
- hybrid SQL + RAG answers
- human-in-the-loop SQL approval
- JWT auth, rate limiting, token budgets, and layered guardrails
- admin observability and cache management
- CI-safe evaluation flows
- AWS deployment with HTTPS custom domains
- CloudWatch monitoring, dashboards, and load-test evidence

The deployed public entry points are:

- Backend: `https://api.aiscientificlabs.com`
- Frontend: `https://rag.aiscientificlabs.com`

Current deployed infrastructure uses:

- ECS Fargate
- ECR
- ALB
- Route 53
- ACM
- RDS PostgreSQL
- S3
- Qdrant Cloud
- Secrets Manager
- CloudWatch Logs, Alarms, and Dashboard widgets

Current deployed revisions verified during the latest validation:

- Backend task definition: `new-adv-rag-backend:25`
- Streamlit task definition: `new-adv-rag-streamlit:16`

The latest consolidated validation summary is stored in:

- `loadtests/results/FINAL_LOADTEST_RESULTS_20260708.md`

## 2. Why This Rebuild Matters

The goal was not to assemble a demo from copied files. The goal was to rebuild a system deeply enough to:

1. explain the architecture credibly
2. debug production failures instead of hand-waving them away
3. make deployment, validation, and iteration repeatable

Most RAG demos stop at:

- upload
- embed
- retrieve
- answer

This project intentionally goes further by covering:

- ingestion dedupe
- hybrid routing
- safer SQL generation
- caching
- operational controls
- observability
- evaluation
- load testing

That is the difference between a prompt demo and a backend system you can discuss as real engineering work.

## 3. Final Product Scope

### User-Facing Capabilities

- answer policy and runbook questions from uploaded documents
- answer structured questions from PostgreSQL
- answer hybrid questions that combine SQL facts and document guidance
- expose `Manual` and `Auto` retrieval behavior in the frontend
- show response metadata including cache and source details

### Backend Capabilities

- ingest local files or uploaded bytes
- compute content hash and skip duplicate documents
- embed chunks with OpenAI embeddings
- index vectors in Qdrant Cloud
- store original document objects in S3
- cache retrieval, SQL generation, SQL result, embeddings, and final answers
- grade and optionally refine retrieval behavior
- validate generated SQL with `sqlglot`

### Operations Capabilities

- admin health checks
- runtime/cache inspection
- cache clearing
- token-budget inspection
- rate-limit inspection
- CloudWatch alarms
- CloudWatch dashboard for screenshots during load tests
- ECS service autoscaling

## 4. Final Architecture

### Main Layers

1. API layer
2. Security and guardrails layer
3. Routing and orchestration layer
4. Retrieval and SQL services layer
5. Storage, vector, and cache layer
6. Evaluation and testing layer
7. Deployment and observability layer

### Runtime Flow

1. Client calls `POST /query`
2. JWT auth, rate limiting, token budgets, restructuring, and safety checks run
3. Router selects `rag`, `sql`, or `hybrid`
4. If `search_mode="auto"`, backend resolves the actual retrieval strategy
5. RAG and/or SQL branch executes
6. SQL branch pauses for approval when needed
7. Final answer is validated and returned with metadata

### Ingestion Flow

1. User uploads a file through `/documents/upload`
2. App computes a content hash
3. Duplicate documents are skipped
4. Document is parsed and chunked by the app
5. Chunks are embedded with OpenAI
6. Vectors are stored in Qdrant Cloud
7. Original object is stored in S3
8. Metadata is saved for future dedupe and traceability

### Responsibility Split

- Application:
  - parsing
  - chunking
  - approvals
  - orchestration
  - cache policy
  - metadata
- OpenAI:
  - embeddings
  - answer generation
  - grading and control logic
- Qdrant:
  - vector storage
  - similarity search
- PostgreSQL:
  - structured data
  - users and auth records
- Redis / Upstash:
  - query-time cache when configured
- S3:
  - original uploaded document objects

## 5. Core Engineering Decisions

### 5.1 Separate Data Systems By Responsibility

- PostgreSQL for structured business data and auth
- Qdrant for vector retrieval
- Redis-style cache for query acceleration
- S3 for durable original document storage

### 5.2 Centralize Ingestion

`IngestionService` orchestrates document indexing instead of scattering ingestion logic across routes and scripts.

### 5.3 Keep Query Cache and Document Dedupe Separate

- `DocCacheService` handles content-hash dedupe and ingestion metadata
- `QueryCacheService` handles query-time caches

### 5.4 Treat SQL As Higher Risk

SQL generation is protected by:

- route-level separation
- AST-based SQL validation via `sqlglot`
- optional human approval
- SQL-generation and SQL-result caching

### 5.5 Treat Retrieval Choice As Backend Policy

The project supports both:

- `Manual` mode for demos and architecture explanation
- `Auto` mode for production-style backend-owned retrieval selection

Response metadata records:

- `requested_search_mode`
- `resolved_search_mode`
- `auto_enabled`
- `auto_strategy_reason`

### 5.6 Use Evidence To Choose Defaults

The practical default is:

- `hybrid + rerank`

The more advanced features remain conditional tools rather than always-on defaults:

- HyDE
- CRAG
- self-reflection

## 6. Key Implementation Areas

### 6.1 Retrieval

Implemented retrieval families:

- dense retrieval
- sparse retrieval
- hybrid retrieval
- reranking
- HyDE
- CRAG
- self-reflective RAG

Important lesson:

- enterprise questions often need both semantic and lexical grounding
- hybrid retrieval is the safest default for mixed corpora
- reranking helps, but must be evaluated against real and noisy data

### 6.2 SQL and Hybrid

Implemented SQL features:

- schema-aware SQL generation
- SQL-generation cache
- SQL-result cache
- AST-based validation with `sqlglot`
- approval flow via `/query/sql/execute`

Hybrid flow supports questions such as:

- "How many P1 incidents breached SLA last month and what is our escalation policy?"

That path combines:

- document retrieval
- SQL generation and approval
- merged final answer synthesis

### 6.3 Guardrails

Implemented layered controls:

- JWT auth
- admin-only upload path
- password hashing
- rate limiting
- token budgets
- input restructuring
- input safety checks
- moderation / redaction
- output validation

### 6.4 Cache and Cost-Saved Semantics

Response payloads expose:

- `cost_saved`
- `llm_cost_saved`
- `infra_cost_saved`

Final semantics:

- fresh response -> saved-cost fields are `0`
- cache hit -> fields show estimated avoided work

This avoids fake "savings" on first-run answers.

## 7. Reimplementation Journey

### Phase 1: Foundation

Built:

- `pyproject.toml`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- app bootstrap and config

Established:

- clean local environment
- dependency management
- service boundaries

### Phase 2: Models and State

Built stable shared contracts:

- request models
- response models
- pending SQL block
- retrieved chunk structures
- graph state

### Phase 3: Storage and Caching

Added:

- local and S3 storage backends
- query cache service
- document cache service

### Phase 4: Ingestion

Implemented:

- document parsing
- chunking
- embedding
- vector upsert
- dedupe orchestration

### Phase 5: Retrieval Services

Implemented:

- dense / sparse / hybrid retrieval
- reranking
- HyDE
- CRAG
- self-reflection hooks

### Phase 6: RAG Path

Built `rag_service.py` to:

- retrieve
- grade / rerank
- build spotlighted context
- synthesize answer
- cache answer
- report metadata

### Phase 7: SQL and Hybrid Path

Built `sql_service.py` and graph logic for:

- SQL-only
- hybrid SQL + RAG
- approval flow

### Phase 8: Security and Admin

Added:

- auth middleware
- rate limiting
- token budgets
- admin endpoints

### Phase 9: Evaluation and CI

Added:

- Pytest coverage
- eval-safe fixtures
- CI-friendly smoke evals

### Phase 10: AWS Deployment and Validation

Completed:

- ECS deployment
- ALB routing
- custom domains
- HTTPS via ACM
- CloudWatch alarms
- CloudWatch dashboard
- load-test evidence capture

## 8. Important Problems Solved

### 8.1 Cache Correctness

Problem:

- answers were at risk of being reused across incompatible retrieval settings

Fix:

- cache keys include retrieval context and relevant flags

### 8.2 SQL Safety

Problem:

- naive string checks are weak protection

Fix:

- moved to AST-based SQL validation with `sqlglot`

### 8.3 Deployment Encoding Failure

Problem:

- deployed ECS requests intermittently failed with timeouts on heavier paths
- root cause was UTF-8 / stdout-stderr encoding behavior in the container runtime

Fix:

- force UTF-8 environment settings
- reconfigure stdout/stderr with safe encoding in backend startup

### 8.4 ECS / ALB Networking

Problem:

- healthy containers can still fail ALB health checks
- subnet, SG, and target-group alignment issues caused real deployment failures

Fix:

- corrected SG ingress
- aligned ECS subnets with ALB-enabled AZs
- validated target-group behavior directly

### 8.5 Streamlit Deployment Drift

Problem:

- Streamlit could serve stale config or older build content if Docker context or `API_BASE_URL` was wrong

Fix:

- corrected build context assumptions
- corrected task-definition environment values
- revalidated live frontend against HTTPS backend domain

### 8.6 SQL Approval State

Problem:

- approval state is in-memory and can go stale across deploy/restart

Fix:

- backend now returns explicit `409` cases such as missing approval context

### 8.7 Load-Test Wrapper UX

Problem:

- local `k6` execution was brittle if `PATH` was not refreshed
- threshold failures produced noisy PowerShell output

Fix:

- hardened `run_k6.ps1` to locate `k6.exe`
- improved threshold-failure messaging

## 9. Final AWS State

Live environment summary:

- Region: `us-east-2`
- ECS cluster: `new-adv-rag-cluster`
- Backend service: `backend-service`
- Streamlit service: `streamlit-service`
- Backend ALB: `backend-alb`
- Streamlit ALB: `streamlit-alb`
- Backend target group: `backend-tg`
- Streamlit target group: `streamlit-tg`
- Backend log group: `/ecs/new-adv-rag-backend`
- Streamlit log group: `/ecs/new-adv-rag-streamlit`
- CloudWatch dashboard: `new-adv-rag-ops`

Latest verified public URLs:

- `https://api.aiscientificlabs.com/health`
- `https://rag.aiscientificlabs.com`

## 10. Validation and Evidence

### 10.1 Local Validation

- local regression suite passed
- evaluation flows validated
- manual preset checks completed

### 10.2 Deployed Runtime Validation

Verified:

- backend health reachable over HTTPS
- frontend reachable over HTTPS
- RAG path works
- SQL approval path works
- hybrid path works
- Auto and Manual modes behave correctly
- cache-hit metadata is visible

### 10.3 CloudWatch Dashboard

Built dashboard:

- `new-adv-rag-ops`

Dashboard includes:

- manual alarm status
- backend ALB response time
- backend ECS CPU and memory
- RDS CPU and connections
- backend ALB 5xx and request volume
- backend target group health
- streamlit ECS CPU
- backend request logs

### 10.4 Load Testing

Saved result artifacts:

- `loadtests/results/FINAL_LOADTEST_RESULTS_20260708.md`
- raw `.txt` outputs for health, RAG, and mixed smoke runs

Observed outcomes:

- health path passed cleanly
- RAG path passed functionally and met threshold on the second 1-minute run
- mixed smoke passed functionally but exceeded the configured p95 latency threshold
- no HTTP failures were observed in the validated runs

### 10.5 ECS Evidence

Captured evidence showed:

- service active
- deployment successful
- `1 running / 0 pending`
- task healthy
- target-group health stable

## 11. What This Project Demonstrates

This project demonstrates:

- backend architecture for GenAI systems
- retrieval tradeoff awareness
- safer SQL generation patterns
- production-minded caching
- deployment on real cloud infrastructure
- monitoring and alerting
- validation through tests, evals, and load tests

The strongest story is not "it works locally." The strongest story is:

- it was rebuilt intentionally
- deployed end-to-end
- monitored in AWS
- load-tested against the live backend
- documented as a repeatable engineering process

## 12. Recommended Interview Framing

One concise framing:

"I rebuilt an enterprise-style RAG backend that supports dense, sparse, and hybrid retrieval; SQL and hybrid routing; SQL approval; layered guardrails; caching; admin observability; AWS deployment; and CloudWatch-backed load-test validation. The main engineering value was not just feature count, but getting the system into a state where it could be safely explained, deployed, monitored, and tested under realistic conditions."

## 13. Next Logical Improvements

- lower mixed-flow latency
- richer cost telemetry from real usage accounting
- admin-triggered real eval runs
- stronger multi-tenant isolation
- deeper observability stack beyond CloudWatch
- Kubernetes deployment assets if needed later

## 14. Bottom Line

This project evolved from an advanced RAG backend into a deployed, monitored, and validated enterprise-style system that is credible for interviews, demos, and future domain adaptation work.
