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

Current deployed revisions verified on July 10-11, 2026:

- Backend task definition: `new-adv-rag-backend:34`
- Backend image: `20260711-context-precision3`
- Streamlit task definition: `new-adv-rag-streamlit:22`
- Streamlit image: `20260711-context-precision2`

The latest consolidated validation summary is stored in:

- `loadtests/results/FINAL_LOADTEST_RESULTS_20260708.md`

The complete evaluation and retrieval hardening chronology—including failed
experiments, evaluator corrections, unseen holdouts, claim auditing, retrieval
repairs, chunk-boundary diagnosis, and the v2 ingestion migration—is documented in
[`EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md`](EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md).

That case study is the authoritative narrative for the July 11 evaluation work.
Intermediate scores elsewhere in this writeup should be read as historical
checkpoints, not as substitutes for the latest timestamped result artifacts.

### 1.1 July 2026 Hybrid Precision and Follow-Up Hardening

The latest change corrected an evaluation and evidence-packaging mismatch in combined SQL + RAG questions without reducing retrieval recall.

Root causes:

- the local hybrid evaluator sent the full SQL + documentation question into document retrieval instead of the focused documentation clause used by the production graph
- SQL rows were represented differently in local and HTTP evaluation paths
- the precision judge compared each document chunk against the entire combined question, incorrectly requiring a runbook chunk to contain SQL values
- the follow-up phrase `after that` was not resolved and could fall through to noisy web retrieval

Implemented fixes:

- hybrid evaluation now uses the same document-question decomposition as production
- SQL evidence is consolidated into one typed `database query` chunk instead of one chunk per row
- hybrid API metadata now exposes both document evidence and the consolidated SQL preview while retaining structured `sql_rows`
- context precision is subquestion-aware: document evidence is scored against the RAG clause and database evidence against the quantitative clause
- failed-mitigation follow-ups transition from the incident runbook to the authoritative on-call escalation policy
- SQL evidence previews explicitly identify the quantitative question they answer
- learner-oriented architecture docstrings were added to request/response contracts, auto-retrieval decisions, hybrid decomposition, evidence packaging, and precision scoring

Deployed evaluation on questions `q-029` through `q-032`, profile `hybrid+rerank+crag`:

| Metric | Before | After |
|---|---:|---:|
| Faithfulness | 1.000 | 1.000 |
| Context precision | 0.625 | 1.000 |
| Context recall | 1.000 | 1.000 |
| Answer relevancy | 0.950 | 0.950 |
| Forbidden violations | 0 | 0 |

Validation evidence:

- 80 unit/integration tests passed
- Ruff and `git diff --check` passed
- Docker backend and Streamlit images built and started successfully
- six frontend presets passed against both local Docker and AWS
- frontend and backend HTTPS health endpoints passed
- AWS health load: 30/30 successful requests, 0% failures, 72.1 ms p95
- hybrid metadata returned the focused retrieval question, scored chunks, SQL rows, database evidence, cache state, and cost-saved breakdowns
- the earlier local checkpoint contained 1,179 Qdrant points; a later direct AWS
  audit found 33,113 points and 366 unique source names, of which 365 were
  reproducible locally as 49 authoritative and 316 noisy sources. These are
  different environments and must not be presented as one corpus measurement.

The unpaced local mixed-load script accelerated after cache hits and reached the intentional per-user rate limit. The resulting 429 responses demonstrate guardrail enforcement; they are not backend crashes or retrieval failures. Capacity testing should use distinct tenant identities or deliberate pacing when the objective is throughput rather than rate-limit validation.

During deployment, backend revision 32 failed before startup because its task definition referenced the removed Secrets Manager key `UPSTASH_REDIS_URL`. Production traffic remained on revision 31. Revision 33 corrected the mapping by exposing secret key `UPSTASH_REDIS_REST_URL` as application environment variable `UPSTASH_REDIS_URL`; revision 34 added the final follow-up-policy transition. Both ECS services reached steady state at `1 running / 0 pending`.

## 2. Why This Rebuild Matters

### Enterprise Repository Refactor

The codebase now follows domain and deployment boundaries instead of concentrating
business logic in a flat services folder. Canonical packages are `app.rag`,
`app.sql`, `app.caching`, `app.ingestion`, and `app.observability`; endpoints live
under `app.api.v1`; evaluation assets are separated into datasets, runners, and
reports; and tests are layered into unit, integration, contract, and e2e areas.

Every maintained Python class and function has a learner note and docstring. CI runs
the idempotent `scripts/add_learner_docs.py` audit and fails if documentation drift
would change the working tree. Legacy import paths remain as thin compatibility
bridges for one migration window so the structural improvement does not become a
breaking release.

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

"I built an enterprise-style RAG backend that supports dense, sparse, and hybrid retrieval; SQL and hybrid routing; SQL approval; layered guardrails; caching; admin observability; AWS deployment; and CloudWatch-backed load-test validation. The main engineering value was not just feature count, but getting the system into a state where it could be safely explained, deployed, monitored, and tested under realistic conditions."

## 13. Next Logical Improvements

- lower mixed-flow latency
- richer cost telemetry from real usage accounting
- admin-triggered real eval runs
- stronger multi-tenant isolation
- deeper observability stack beyond CloudWatch
- Kubernetes deployment assets if needed later

## 14. Bottom Line

This project evolved from an advanced RAG backend into a deployed, monitored, and validated enterprise-style system that is credible for interviews, demos, and future domain adaptation work.

## 15. Ambiguous-Query and CRAG Hardening (July 11, 2026)

A live out-of-distribution audit exposed an important blind spot: short questions such as
`How do I scale?` entered hybrid retrieval even though they did not identify what should be
scaled. In the mixed 50-signal/324-noise corpus, lexical and semantic similarity then promoted
unrelated PDFs. The old aggregate CRAG grade could rate the complete context highly when only
one chunk was useful.

The corrective design now:

- requests clarification before retrieval when an action has no resolvable target;
- returns route `clarification` with no chunks, sources, embedding, LLM, or SQL cost;
- permits explicit questions such as `How do I scale a Kubernetes Deployment?` to proceed;
- removes known non-Kubernetes corpus noise before reranking for explicit Kubernetes queries;
- grades every CRAG chunk independently and records score, relevant count, total, and ratio;
- filters chunks that fail the configured CRAG relevance threshold before generation;
- adds route, forbidden-source, and source-precision contracts to the evaluation runner;
- adds ten out-of-distribution ambiguity cases and Streamlit component tests.

Validation evidence for this change:

- Ruff: passed;
- automated suite: 105 passed;
- strict fixture ambiguity evaluation: 10/10 clarification cases passed with zero route or
  forbidden-source violations;
- live Docker ambiguity matrix: 10/10 returned clarification and zero evidence chunks;
- live preset smoke: all six presets returned HTTP 200 on the expected RAG, SQL, or hybrid route;
- stale SQL approval: correctly returned HTTP 409;
- local backend and Streamlit health: HTTP 200;
- k6 health smoke: 50/50 requests passed, 0% failures, p95 10.75 ms.

The broader live retrieval matrix also exposed repeated cross-encoder construction. The
reranker now caches one model instance per worker and model name, preventing transformer
weights from being reloaded for every request. A regression test verifies model reuse. The
original 21-question run exceeded its 10-minute harness limit, so no aggregate score is claimed
for that incomplete run; it remains a release gate to rerun with an explicit per-case timeout.

These results are regression evidence, not a claim that arbitrary-question retrieval is
perfect. Production evaluation must continue to expand with unseen queries, source-level
labels, adversarial noise, and latency/cost budgets.

### 15.1 Authority and Retrieval Follow-up

The 21-question live matrix then identified three concrete weaknesses. Static Kubernetes
questions could fall through to third-party web pages, broad security retrieval omitted the
RBAC document, and Self-RAG displayed an uncertainty prefix despite having usable evidence.
The follow-up change restricts web fallback to explicitly current Cilium, EKS, or Argo CD
questions; filters results through an authoritative-domain and path allowlist; adds an RBAC and
least-privilege rescue query for cluster-security requests; preserves complementary security
chunks through final filtering; and only shows uncertainty when no relevant evidence survives.

Focused live Docker results after the change:

- control-plane source precision improved from 0.20 to 1.00;
- implicit StatefulSet source precision improved from 0.50 to 1.00;
- security context recall improved from 0.25 to 0.75, with RBAC and least privilege present;
- the three current-web CRAG cases achieved source precision 1.00 and context recall 1.00;
- current-web aggregate: faithfulness 0.747, context precision 0.656, answer relevancy 0.702;
- automated suite: 111 tests passed, including trusted web-domain/path regressions.

The heuristic scorer remains a lexical smoke scorer and must not be compared directly to an
LLM/Ragas score. Release evidence should label the scoring backend prominently.

### 15.2 Frozen Challenge Baseline and Safeguards

A separate 40-question dataset with complete reference answers produced a deliberately honest
first-run baseline: 38 completed, two runtime failures, two route failures, one forbidden-source
failure, source precision 0.768, context precision 0.842, context recall 0.919, and answer
relevancy 0.884 with the LLM scorer. The failures revealed SQL false positives, unbounded SQL
result materialization, missing clarification variants, answers generated after CRAG removed all
evidence, and workload-identity retrieval gaps.

The development-partition fixes now:

- require specific database phrasing instead of treating every `which` plus `users` question as SQL;
- cap SQL result sets at 200 rows before caching or LLM composition;
- clarify unresolved performance, architecture, and change-scope requests;
- abstain without an answer-model call when no reliable chunks survive;
- rescue dedicated ServiceAccount and RBAC evidence for workload-identity questions;
- remove Dashboard catalog noise when another authoritative source survives;
- use cache schema 21 so stale evidence decisions cannot mask the new behavior.

Post-fix verification: 119 automated tests passed; all 28 development questions completed with
zero route, forbidden-answer, or forbidden-source violations; affected focused cases achieved
source precision 1.00. A final source-policy pass removed the extra StatefulSet evidence from the
durable-Service paraphrase and strengthened grounded generation against requests for unrelated
sources. The original `q-129` through `q-140` results remain the recorded holdout
baseline and were not used to design the fixes.
