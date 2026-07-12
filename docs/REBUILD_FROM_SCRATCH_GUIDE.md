# Enterprise Advanced RAG: Rebuild From Scratch

This guide explains how a new engineer can reconstruct the current project in dependency order,
verify each layer, and reach the same production-minded design without copying accidental legacy
patterns.

It is an implementation guide, not a promise that every environment uses identical resource
names. Use these companion documents when you need operational details:

- [`COMMANDS_RUNBOOK.md`](COMMANDS_RUNBOOK.md) for copy-ready commands;
- [`AWS_DEPLOYMENT.md`](AWS_DEPLOYMENT.md) for current AWS resources and release procedures;
- [`WRITEUP.md`](WRITEUP.md) for the architecture and engineering narrative;
- [`EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md`](EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md)
  for the failures that led to the current retrieval, chunking, and evaluation design;
- [`../evals/reports/EVALUATION_SUMMARY_20260712.md`](../evals/reports/EVALUATION_SUMMARY_20260712.md)
  for curated evaluation evidence.

## 1. What You Are Building

The final application supports:

- authenticated RAG, SQL, and combined SQL+RAG answers;
- dense, sparse, hybrid, reranked, HyDE, CRAG, and Self-RAG retrieval policies;
- clarification before retrieval when a short question lacks a resolvable subject;
- safe read-only SQL generation with human approval;
- sentence-aware document chunking and metadata-rich Qdrant ingestion;
- local or S3 document storage;
- PostgreSQL, Qdrant, and optional Upstash Redis;
- FastAPI and Streamlit containers;
- deterministic CI gates plus LLM-judged release evaluations;
- AWS ECS, RDS, Qdrant Cloud, HTTPS, CloudWatch, and load-test workflows.

The public product routes remain `rag`, `sql`, and `hybrid`. `clarification` is an internal safe
outcome: it asks the user for missing detail without spending retrieval, embedding, SQL, or answer
generation cost.

## 2. Prerequisites

Install:

- Python 3.12 or newer;
- Git;
- Docker Desktop with Compose;
- AWS CLI v2 for cloud deployment;
- k6 for load testing;
- valid OpenAI credentials;
- optional Tavily, Upstash, S3, and Qdrant Cloud credentials.

From the repository root, create the environment:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Copy `.env.example` to `.env`, then supply real values locally. Never commit `.env`, access keys,
tokens, database passwords, or task-definition payloads containing resolved secrets.

Minimum local values:

```dotenv
OPENAI_API_KEY=replace-me
DATABASE_URL=postgresql://postgres:postgres@localhost:5434/adv_rag
QDRANT_URL=http://localhost:6334
QDRANT_COLLECTION=new_adv_rag_documents_v2
JWT_SECRET=replace-with-a-long-random-value
LLM_MODEL_ANSWER=gpt-4o
LLM_MODEL_GRADER=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

Upstash is optional. When it is absent, the application must remain functional with local or
in-process fallbacks; cache availability must not determine answer correctness.

## 3. Current Repository Contract

Build toward this structure:

```text
app/
  api/v1/          versioned FastAPI endpoints
  caching/         query and document cache adapters
  core/            LangGraph state and orchestration
  ingestion/       parsing, sentence-aware chunking, indexing
  middleware/      authentication and rate limiting
  observability/   cost and runtime telemetry
  rag/             retrieval, generation, advanced RAG policies
  security/        input/output guardrails and token budgets
  sql/             governed SQL and pending-approval state
  storage/         local and S3 storage adapters
db/
  migrations/      ordered idempotent SQL migrations
  seeds/           environment-safe seed assets
evals/
  datasets/        development, regression, and sealed datasets
  runners/         fixture, local, service, and HTTP runners
  reports/         curated summaries; raw results are Git-ignored
infra/
  docker/          backend and Streamlit Dockerfiles
  ecs/             ECS task definitions and runbook
  terraform/       infrastructure-as-code foundation
tests/
  unit/ integration/ contract/ e2e/ fixtures/
ui/streamlit/      frontend application and components
scripts/           seeding, corpus audit, manifest, smoke utilities
loadtests/         k6 scripts and retained summaries
```

Files under `app/services/` are compatibility facades for older import paths. New implementation
logic belongs in the domain packages above; do not create a second implementation in a facade.

## 4. Phase 1: Foundation and Configuration

Create these first:

- `pyproject.toml` with Python 3.12 and runtime/dev dependencies;
- `app/config.py` using Pydantic settings;
- `app/models.py` for stable API and internal contracts;
- `app/main.py` with `/health` and versioned routers;
- `ui/streamlit/app.py`;
- `.env.example`, `.gitignore`, and `.dockerignore`.

Configuration groups must cover models, PostgreSQL, Qdrant, Redis, storage, JWT, rate limits,
token budgets, retrieval defaults, and AWS settings. Validate required production values at
startup rather than discovering missing secrets during a query.

Define typed contracts early, including `QueryRequest`, `ChatResponse`, `RetrievedChunk`, response
metadata, pending SQL, CRAG evaluation, reflection output, and conversation turns. Keep graph state
in `app/core/state.py`; avoid ad hoc dictionaries flowing between nodes.

Completion gate:

```powershell
.\.venv\Scripts\python.exe -m ruff check app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Invoke-RestMethod http://localhost:8000/health
```

## 5. Phase 2: Persistence, Storage, and Cache Boundaries

Implement PostgreSQL migrations and connection helpers before SQL routing. The existing numbered
SQL migrations are ordered and idempotent; production evolution should eventually use Alembic or
another version-tracked migration system.

Implement storage through:

- `app/storage/storage_backend.py`;
- `app/storage/local_storage.py`;
- `app/storage/s3_storage.py`.

Implement separate cache responsibilities:

- `app/caching/query_cache.py` for intent, answer, SQL, and embedding caches;
- `app/caching/document_cache.py` for ingestion identity and document metadata.

Never use query-cache contents as the source of truth for whether a document exists in a Qdrant
collection. Cache keys must include a schema version and all settings that can change behavior.
Upstash exhaustion or a changed URL should reduce cache performance, not corrupt retrieval.

Completion gate: migrations run twice safely, storage adapters round-trip a test object, cache
miss/hit/clear paths pass, and the application still works when Redis is unavailable.

## 6. Phase 3: Ingestion and Sentence-Aware Chunking

Implement ingestion in:

- `app/ingestion/document_processor.py`;
- `app/ingestion/service.py`;
- `app/rag/embedding_service.py`;
- `app/rag/vector_store.py`.

The required flow is:

1. accept a file path or uploaded bytes;
2. normalize and validate the type;
3. compute a content hash;
4. extract text from TXT, HTML, PDF, or DOCX;
5. split text near sentence boundaries with deterministic overlap;
6. attach source, document, chunk, authority, and ingestion metadata;
7. embed each chunk;
8. upsert deterministic point IDs into the selected Qdrant collection;
9. store the original document;
10. record collection-scoped ingestion metadata.

Do not return to fixed character windows that begin in the middle of words or sentences. The
current chunker prefers sentence boundaries, falls back to word boundaries, and keeps overlap
coherent. Add structure-aware handling later for headings, tables, lists, code, or parent-child
retrieval; sentence awareness is the safe baseline, not the only possible strategy.

Each Qdrant payload should include at least:

- `source` and `text`;
- content/document identity;
- chunk index and total chunks;
- authority or corpus tier;
- ingestion version and target collection;
- page or section information when extraction provides it.

Deduplication must be content-based and scoped to collection plus ingestion version. A document
present in a legacy collection must not be skipped when building a new collection.

Completion gate: parser tests, sentence-boundary tests, deterministic-ID tests, metadata tests,
duplicate-ingestion tests, and collection-isolation tests pass.

## 7. Phase 4: Blue/Green Corpus Construction

Never destroy the working collection while testing a chunking or metadata change. Build a new
collection such as `new_adv_rag_documents_v2`, validate it, switch runtime configuration, and keep
the previous collection for rollback.

Use a manifest rather than random folder discovery:

```powershell
.\.venv\Scripts\python.exe scripts\seed_db.py `
  --manifest seed\manifests\aws_successful_corpus.json `
  --collection new_adv_rag_documents_v2
```

The seeder is resumable. Do not add `--wipe` when continuing an interrupted run. Large PDFs should
be processed one document at a time with per-document cleanup; retry transport failures without
discarding already indexed sources.

Audit the finished collection:

```powershell
.\.venv\Scripts\python.exe scripts\audit_qdrant_corpus.py `
  --url http://localhost:6334 `
  --collection new_adv_rag_documents_v2 `
  --output .cache\qdrant_v2_audit.json
```

Verify unique authoritative/noisy source counts, missing payload fields, duplicate chunks,
unexpected sources, point totals, and retrieval from representative documents. The validated v2
reference corpus contained 49 authoritative and 316 noisy manifest sources; treat those as
provenance for that run, not as a universal product requirement.

## 8. Phase 5: Retrieval Foundation

Implement:

- dense search in `app/rag/vector_store.py`;
- sparse token vectors in `app/rag/sparse_vector.py`;
- reciprocal-rank or equivalent hybrid fusion;
- cross-encoder reranking in `app/rag/reranking.py`;
- conversation-aware question rewriting in `app/rag/conversation_context.py`;
- authority and forbidden-source filtering in `app/rag/service.py`.

Cache one reranker model per worker/model name. Reconstructing transformer weights on every query
causes latency and memory failures.

Retrieval must preserve enough candidates for multi-document questions while excluding unrelated
large-PDF noise. Source filtering should be policy-based and tested; do not hardcode one answer or
one filename for a known evaluation question.

Completion gate: dense, sparse, hybrid, reranking, source filtering, conversation rewrite, and
multi-document evidence tests pass against both relevant and adversarial chunks.

## 9. Phase 6: Advanced RAG Policies

Add advanced capabilities independently:

- `app/rag/hyde.py` creates a hypothetical answer used only for retrieval;
- `app/rag/crag.py` grades individual chunks and removes weak evidence;
- `app/rag/self_reflective.py` checks whether retrieval or generation needs correction;
- `app/rag/web_search.py` provides controlled current-information fallback;
- `app/rag/system_prompt.py` defines grounded answer behavior.

HyDE, CRAG, and Self-RAG are conditional tools, not badges to enable on every question. CRAG must
grade per chunk rather than assigning a misleading high score to a mixed context. If no reliable
evidence survives, abstain without calling the answer model.

Web fallback must require a genuinely current question and enforce trusted domain/path policy. A
static Kubernetes question should not escape to arbitrary web pages merely because local retrieval
was weak.

## 10. Phase 7: Clarification, Routing, and Auto Retrieval

Implement routing in:

- `app/rag/clarification.py`;
- `app/rag/router.py`;
- `app/rag/auto_retrieval.py`;
- `app/rag/hybrid_question.py`.

Resolve clarification before retrieval when an action has no subject, for example “How do I scale?”
or “Can you rotate it now?” without usable conversation context. Explicit questions such as “How
do I scale a Kubernetes Deployment?” proceed normally.

Auto mode must record:

- requested and resolved search modes;
- enabled advanced policies;
- a concise strategy reason.

Do not route to SQL just because a question contains words such as “which” or “users.” SQL intent
requires evidence that the user is asking about structured application data.

Completion gate: vague new questions clarify; explicit equivalents retrieve; follow-ups resolve
from bounded conversation context; SQL false positives are rejected; metadata explains the choice.

## 11. Phase 8: Governed SQL and Human Approval

Implement:

- `app/sql/service.py` for schema-aware generation, `sqlglot` validation, and execution;
- `app/sql/pending_store.py` for resumable approval state;
- SQL and hybrid nodes in `app/core/graph.py`.

Allow only bounded, read-only queries. Reject DDL, DML, stacked statements, unsafe functions, and
unapproved access. Cap materialized results before caching or sending them to an LLM.

The first request returns a pending SQL block. `POST /query/sql/execute` must validate that the
approval belongs to the authenticated user and the current resumable query. A stale approval after
restart correctly returns HTTP 409 and asks the caller to rerun the original question.

## 12. Phase 9: Security and Middleware

Build the request path from:

- JWT authentication;
- per-user rate limiting;
- daily token budget enforcement;
- input normalization and restructuring;
- prompt-injection and unsafe-input checks;
- moderation/redaction;
- spotlighting of untrusted retrieved content;
- grounded output validation.

Keep controls independently testable. Never claim a “nine-layer” security design merely by
counting files; document the actual order, failure response, owner, and observable evidence for
each control.

## 13. Phase 10: LangGraph and APIs

Implement graph state in `app/core/state.py` and orchestration in `app/core/graph.py`. The graph must
support RAG, SQL, combined SQL+RAG, clarification, pending approval, and final response formatting.

Expose:

- `POST /auth/register` and `POST /auth/login`;
- `POST /query` and `POST /query/sql/execute`;
- `POST /documents/upload`;
- `/admin/health`, cache, runtime, budget, and rate-limit endpoints;
- `GET /health` for container and load-balancer health checks.

Routes validate and delegate; they must not reimplement ingestion, retrieval, or SQL logic.

## 14. Phase 11: Streamlit Frontend

The frontend must support login, auto/manual configuration, presets, follow-up context, SQL
approval, and answer/source/chunk/metadata/raw views. It should display public route labels without
turning internal clarification into a confusing fourth product workflow.

Test both successful and failure UX: expired login, backend unavailable, clarification response,
empty evidence, stale SQL approval, and source rendering.

## 15. Phase 12: Automated Tests

Organize tests by purpose:

- unit: policies and pure behavior;
- integration: API, persistence, caches, and service composition;
- contract: repository layout, dataset checksums, CI/evaluation contracts;
- e2e: Streamlit components and future real-browser flows;
- fixtures: deterministic external-service replacements.

Every production bug should receive a general regression test. Do not write a test that only
recognizes one question string.

Run the complete local gate:

```powershell
.\.venv\Scripts\python.exe -m ruff check app evals Eval scripts ui tests
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

At the final July 12 checkpoint, Ruff passed and 167 tests passed. Test count is provenance, not a
fixed target; future improvements should increase or reorganize it.

## 16. Phase 13: Evaluation That Cannot Hide Failures

Build evaluation contracts with:

- expected route;
- expected and forbidden sources;
- reference/golden answer where applicable;
- atomic evidence requirements;
- forbidden answer patterns;
- per-question and aggregate thresholds.

Source precision and recall must use exact normalized source identity, not substring matching.
Prevent impossible scores: absent context cannot receive retrieval credit, and source-less
clarification makes source metrics non-applicable rather than perfect or zero.

PR CI uses deterministic fixture evaluations with exact source precision and recall gates:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile hybrid `
  --filter hybrid `
  --mode fixture `
  --scorer heuristic `
  --strict `
  --min-source-precision 1.0 `
  --min-source-recall 1.0
```

LLM-judged faithfulness, context precision/recall, and answer relevancy belong in nightly or
release validation because they cost money and vary between runs.

Use this dataset lifecycle:

1. develop against seed and regression suites;
2. freeze code, collection, models, cache schema, and dataset checksum;
3. run a sealed holdout once;
4. record the first valid result without hiding failures;
5. move findings into a named regression suite;
6. create a new sealed holdout for the next unbiased measurement.

Never repeatedly tune and rerun a sealed set while still calling it unseen. Raw JSON reports stay
local or in access-controlled CI artifacts; Git stores curated summaries.

## 17. Phase 14: Local and Docker End-to-End Validation

Start infrastructure only when developing outside containers:

```powershell
docker compose up -d postgres qdrant
```

Run migrations/users without ingestion when needed:

```powershell
.\.venv\Scripts\python.exe scripts\seed_db.py --no-ingest
```

Build the actual Compose service names (`app`, not `backend`):

```powershell
docker compose build app streamlit
docker compose up -d --force-recreate app streamlit
docker compose ps
Invoke-RestMethod http://localhost:8003/health
Invoke-WebRequest http://localhost:8501/_stcore/health
```

The port mapping is:

- backend: host `8003` to container `8000`;
- Streamlit: `8501`;
- PostgreSQL: host `5434` to container `5432`;
- Qdrant: host `6334` to container `6333`.

Validate registration/login, all presets, new unseen questions, clarification, follow-ups, RAG,
SQL approval, combined SQL+RAG, sources, chunks, metadata, costs, cache miss/hit behavior, and stale
approval handling. Do not treat a green `/health` response as proof that retrieval works.

## 18. Phase 15: AWS Release

Only deploy a commit that passed the local gates. The release sequence is:

1. verify AWS identity, region, account, cluster, repositories, and secret names;
2. build immutable backend and Streamlit image tags;
3. push images to ECR;
4. generate task-definition JSON without corrupting UTF-8 or exposing secrets;
5. register new task revisions;
6. update backend and wait for healthy ALB targets;
7. run backend smoke and evaluation checks;
8. update Streamlit and verify it targets the new backend;
9. verify HTTPS, logs, alarms, task count, and rollback revision.

AWS uses RDS, Qdrant Cloud, optional Upstash, S3, ECS Fargate, ECR, ALB, ACM, Route 53,
Secrets Manager, and CloudWatch. Terraform should become the authoritative infrastructure path;
hand-maintained task JSON remains a compatibility artifact until migration is complete.

Follow [`AWS_DEPLOYMENT.md`](AWS_DEPLOYMENT.md) rather than copying account-specific ARNs from an
old terminal session.

## 19. Phase 16: Load, Resilience, and Release Evidence

Run health, authenticated RAG, SQL, combined, cache-hit/miss, and sustained workloads. Start small:

```powershell
.\loadtests\run_k6.ps1 -Script "health.js" -Duration "30s" -Vus "2"
.\loadtests\run_k6.ps1 -Script "query_rag.js" -Username "user@example.com" -Password "replace-me" -Duration "1m" -Vus "2"
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "user@example.com" -Password "replace-me" -Duration "1m" -RagVus "1" -SqlVus "1" -HybridVus "1"
```

Capture commit SHA, image digest, task revision, configuration identifiers, corpus counts, models,
latency percentiles, error rate, cost, CloudWatch evidence, and rollback result. A health-only load
test proves availability of one endpoint, not generation capacity.

## 20. Definition of Done

A rebuild is ready for presentation when:

- the corpus can be reproduced from a manifest;
- chunk/source metadata is auditable;
- retrieval handles explicit, vague, noisy, multi-document, and follow-up questions;
- SQL is read-only, bounded, and approval-controlled;
- cache loss does not change correctness;
- all deterministic CI gates and automated tests pass;
- a sealed evaluation is used honestly;
- Docker frontend/backend workflows pass;
- AWS HTTPS, tasks, targets, logs, alarms, and rollback are verified;
- load results and limitations are documented;
- raw generated reports and secrets are excluded from Git.

## 21. Common Failure Modes

- Building RAG prompts before validating chunks and source metadata.
- Using filename presence in a cache as proof that v2 vectors exist.
- Wiping a collection when a resumable ingestion should continue.
- Treating sentence-aware chunking as sufficient for tables, code, and every document type.
- Enabling every advanced RAG feature for every question.
- Letting CRAG score a mixed context only once instead of grading each chunk.
- Routing vague action questions before asking what object the user means.
- Optimizing known eval questions instead of adding generalized policies.
- Reporting aggregate success while per-question failures remain hidden.
- Comparing heuristic fixture scores directly with LLM-judge scores.
- Reusing a sealed holdout until it appears perfect.
- Building `docker compose ... backend` when the service is named `app`.
- Assuming an ECS steady-state timeout means the service failed without inspecting rollout/events.
- Committing raw reports, `.env`, resolved task JSON, or credentials.

## 22. Recommended Learning Order

If the entire system feels large, learn it in this order:

1. request/response models and configuration;
2. parsing, chunking, embeddings, and Qdrant payloads;
3. dense, sparse, hybrid, and reranking;
4. grounded generation and source filtering;
5. clarification and routing;
6. HyDE, CRAG, Self-RAG, and controlled web fallback;
7. SQL validation and approval;
8. LangGraph orchestration;
9. API security, caching, and observability;
10. evaluation contracts and sealed holdouts;
11. Docker, AWS, monitoring, and load testing.

That sequence keeps high-level AI behavior grounded in verified data and infrastructure rather
than building an impressive interface over unreliable evidence.
