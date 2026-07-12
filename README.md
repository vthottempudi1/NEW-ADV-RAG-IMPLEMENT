<div align="center">

# New Advanced RAG Implement

Production-minded enterprise RAG backend with hybrid retrieval, SQL routing, human-in-the-loop SQL approval, `sqlglot`-based SQL safety, AWS deployment, evaluation workflows, and GitHub Actions CI.

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Qdrant](https://img.shields.io/badge/Qdrant-vector_search-DC244C)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-structured_data-4169E1)
![LangGraph](https://img.shields.io/badge/LangGraph-orchestration-1C3C3C)
![CI](https://img.shields.io/badge/CI-GitHub_Actions-success)

**Enterprise RAG + Text-to-SQL + Hybrid Routing + Guardrails + HITL**

</div>

Built with FastAPI, PostgreSQL, Qdrant, Upstash Redis with in-memory fallback, LangGraph, OpenAI, Docker, Pytest, ECS Fargate, Route 53, ACM, and CloudWatch.

Operational policies: [Security](SECURITY.md) · [Data handling](docs/DATA_HANDLING.md) · [Reliability and recovery](docs/RELIABILITY.md) · [AWS deployment](AWS_DEPLOYMENT.md)

This repository is designed to demonstrate the kind of engineering depth hiring managers usually look for in strong GenAI backend projects:

- advanced retrieval beyond basic vector search
- safer SQL generation with explicit approval flow
- security and guardrails as a layered system
- operational visibility through admin endpoints and caching
- evaluation and CI, not just demo-time prompting

## Why This Project Stands Out

Most RAG demos stop at upload, embed, retrieve, answer.

This project goes further by combining:

- unstructured document retrieval
- structured SQL question answering
- hybrid SQL + RAG responses
- duplicate-safe ingestion
- multi-tier caching
- guardrails and operational controls
- evaluation-driven retrieval tuning
- CI validation for both tests and eval-smoke runs

That makes it much closer to a real enterprise AI backend than a basic chatbot demo.

## Core Highlights

- Advanced retrieval stack: dense, sparse, hybrid, HyDE, reranking, CRAG, and Self-Reflective RAG (SRAG)
- Dual retrieval experience: `Manual` mode for feature demos and `Auto` mode for backend-selected production retrieval
- Human-in-the-loop SQL: LangGraph interrupt flow pauses SQL execution until approved
- Safer Text-to-SQL: `sqlglot` AST validation allows only safe read-only query shapes
- 9-layer security pipeline: validation, auth, rate limits, token budgets, input restructuring, prompt-injection checks, moderation/redaction, hardened prompt/context isolation, and output validation
- 5 active cache tiers: RAG answer, SQL generation, SQL result, approved SQL/hybrid answer, and embeddings
- Duplicate-safe ingestion: SHA-256 content hashing prevents re-indexing the same document
- Admin observability: health, cache stats, cache clear, budget stats, runtime info, and rate-limit inspection
- Production deployment: HTTPS custom domains, ECS Fargate services, ALBs, Route 53, ACM, S3, RDS, and Qdrant Cloud
- Reliability controls: ECS autoscaling plus CloudWatch alarms for backend, Streamlit, ALB, and RDS
- Saved-cost telemetry: estimated `cost_saved`, `llm_cost_saved`, and `infra_cost_saved` on cache hits
- Evaluation-ready: fixture-safe eval pipeline plus real corpus testing workflows
- CI passing: GitHub Actions runs `pytest` plus eval-smoke matrix jobs

## What It Can Answer

- RAG questions
  Example: "What does our escalation policy say for P1 incidents?"

- SQL questions
  Example: "How many P1 incidents were resolved last quarter?"

- Hybrid questions
  Example: "How many P1 incidents breached SLA last month and what is our escalation policy?"

That third class is the important one. It shows the system can combine operational data with document-grounded guidance in one answer.

The deployed application also supports two operator-facing modes:

- `Manual`: useful for demos when you want to explicitly show `hybrid`, `dense`, `HyDE`, `CRAG`, or `SRAG`
- `Auto`: useful for production-style behavior where the backend selects the retrieval strategy based on question shape

## Architecture

### High-Level Flow

1. User calls `POST /query`
2. Auth and guardrails run
3. Router picks `rag`, `sql`, or `hybrid`
4. LangGraph orchestrates the correct path
5. RAG and/or SQL execution happens
6. Final answer is validated and returned with metadata

### Main Layers

1. API layer
   FastAPI routes for auth, query, admin, and document upload

2. Security and guardrails layer
   Input validation, JWT auth, rate limiting, token budgets, input safety, moderation, prompt hardening, spotlighting, output validation

3. Orchestration layer
   LangGraph flow for `rag`, `sql`, and `hybrid`

4. Retrieval layer
   Dense, sparse, hybrid, HyDE, CRAG, SRAG, reranking

5. Data layer
   PostgreSQL for structured data and users, Qdrant for vectors, Redis-style cache for query-time acceleration

6. Evaluation and CI layer
   Pytest, fixture-based eval-smoke runs, GitHub Actions

### Architecture Diagram

```text
User / Client
     |
     v
FastAPI API Layer
  |-- /auth
  |-- /documents/upload
  |-- /query
  |-- /admin
     |
     v
Security + Guardrails
  |-- validation
  |-- JWT auth
  |-- rate limiting
  |-- token budgets
  |-- input safety
  |-- moderation/redaction
  |-- output validation
     |
     v
LangGraph Orchestration
  |-- RAG route
  |-- SQL route
  |-- Hybrid route
     |
     +------------------------+
     |                        |
     v                        v
Retrieval Layer           SQL Layer
  |-- dense                  |-- schema context
  |-- sparse                 |-- LLM SQL generation
  |-- hybrid                 |-- sqlglot AST validation
  |-- HyDE                   |-- execution after approval
  |-- CRAG
  |-- SRAG
  |-- reranking
     |                        |
     +-----------+------------+
                 |
                 v
            Final Response
```

## Retrieval Features

### Dense Retrieval

Semantic vector search over embedded document chunks in Qdrant.

### Sparse Retrieval

Keyword-oriented retrieval for exact operational terms, commands, and troubleshooting strings.

### Hybrid Retrieval

Combines dense and sparse signals. This is the best default retrieval family for mixed enterprise corpora.

### HyDE

Generates hypothetical answer-like text to improve retrieval on vague semantic questions.

### Reranking

Improves chunk ordering after retrieval. Especially useful when the corpus contains large amounts of distractor content.

### CRAG

Grades retrieval quality and supports corrective behavior such as retrying retrieval or falling back to web search when configured.

### Self-Reflective RAG (SRAG)

Lets the system reflect on answer quality and optionally regenerate with a refined question.

## SQL + Hybrid Capabilities

### Text-to-SQL

The system can generate SQL from natural-language operational questions using database schema context.

### `sqlglot` Safety Layer

Generated SQL is parsed as an AST and only safe, single-statement, read-only query structures are allowed. This is stronger than naive keyword filtering and is a meaningful production hardening step.

### Human-in-the-Loop SQL Approval

SQL execution does not have to happen immediately. The graph can pause and return a `pending_sql` block, and execution continues only after explicit approval through `POST /query/sql/execute`.

### Hybrid SQL + RAG Answers

For questions that need both database facts and document-grounded policy/runbook context, the system combines both into one answer.

## 9-Layer Security Pipeline

This repo intentionally highlights security and guardrails because hiring managers usually want to know whether a project is just "LLM glue" or something closer to a safe backend.

Implemented layers:

1. Request/model validation
   Pydantic request validation and typed API contracts

2. JWT authentication
   Protected query and admin routes

3. Rate limiting
   Per-user rate limiting with Redis-backed sliding window behavior

4. Token budgets
   Daily per-user token budget checks

5. Input restructuring
   Oversized inputs are normalized and token-count controlled before the main flow

6. Prompt-injection / unsafe input checks
   Blocks patterns like "ignore previous instructions" and "reveal your system prompt"

7. Moderation and redaction
   Input is cleaned and simple PII redaction is applied

8. Hardened prompt + spotlighting
   Retrieved chunks are treated as untrusted context and wrapped in explicit document boundaries

9. Output validation
   Prevents unsafe response patterns such as leaking hidden prompt/instruction content

These are nine implemented defensive checkpoints, not nine independent security products. Input injection checks, PII redaction, and output checks are intentionally lightweight and primarily pattern-based; they provide a practical baseline that should be augmented with stronger policy engines or model-based classifiers for higher-risk production environments.

## Caching Topology

The application actively uses 5 query-time cache tiers:

- `rag_answer`
  caches full RAG answers with retrieval context included in the cache key

- `sql_gen`
  caches generated SQL

- `sql_result`
  caches SQL execution results

- `approved_answer`
  caches completed SQL and hybrid answers only after the human approval flow finishes

- `embedding`
  caches embeddings for repeated text

The cache service also reserves an `intent` namespace, but the current deterministic intent router does not read or write that tier. It is therefore not counted among the five active tiers.

Important design note:

- query-time cache is separate from document deduplication
- document dedupe is handled by `DocCacheService` using content hashing and metadata storage

## Ingestion Pipeline

The ingestion path is intentionally centralized in `IngestionService`.

Flow:

1. uploaded file arrives at `/documents/upload`
2. SHA-256 content hash is computed
3. duplicate documents are skipped
4. document is parsed and chunked
5. chunk text is embedded
6. vectors are upserted into Qdrant
7. ingestion metadata is saved for future dedupe checks

This is a stronger design than scattering ingestion logic across scripts and routes.

## Evaluation Strategy

This repo includes both:

- real retrieval evaluation workflows for local analysis
- fixture-based eval-smoke runs for CI safety

Why that matters:

- real evals help choose the best retrieval architecture
- CI eval-smoke protects the repo from basic regression without depending on live external APIs

Practical outcome from the implemented evaluation flow:

- `hybrid + rerank` is the strongest default profile
- HyDE, CRAG, and SRAG are better treated as conditional policies rather than always-on defaults

Production evaluation artifacts can record the Git commit, environment, collection, model names, and confirmed corpus composition. For example:

```powershell
python -m evals.runners.run `
  --profile all `
  --mode http `
  --scorer llm `
  --api-base "https://api.example.com" `
  --environment production `
  --true-documents 50 `
  --noisy-documents 324
```

Provenance fields deliberately exclude credentials and API keys.

Current evaluation governance:

- PR CI uses deterministic fixtures and requires source precision/recall of `1.000`;
- LLM-judged metrics run during nightly or release validation;
- strict thresholds are checked per question and in aggregate;
- consumed holdouts move into regression and checksummed sealed sets run once;
- raw JSON stays local or in access-controlled CI artifacts;
- versioned evidence is in [the curated July 12 evaluation summary](evals/reports/EVALUATION_SUMMARY_20260712.md).

The latest complete local validation passed Ruff, all five deterministic CI evaluation
partitions, and 172 automated tests. The consumed sealed-v5 findings regression passed strict gates
with 0.975 faithfulness, 1.000 context precision, 0.979 context recall, 1.000 answer relevancy, and
1.000 source precision/recall.

## Project Structure

```text
app/
  api/v1/          # Versioned FastAPI endpoints
  core/            # LangGraph orchestration and shared state
  rag/             # Retrieval, reranking, HyDE, CRAG, Self-RAG, vectors
  sql/             # Governed Text-to-SQL and approval persistence
  security/        # Input/output guardrails and token budgets
  caching/         # Query and document caches
  ingestion/       # Parsing, chunking, embedding, and indexing
  storage/         # Local and S3 storage adapters
  observability/   # Cost and operational telemetry
db/
  migrations/
  seeds/
tests/
  unit/
  integration/
  contract/
  e2e/
  fixtures/
evals/
  datasets/
  runners/
  reports/
ui/
  streamlit/
infra/
  docker/
  ecs/
  cloudwatch/
  terraform/
scripts/
loadtests/
docs/
.github/workflows/
```

See [Enterprise Repository Structure](docs/ENTERPRISE_REPOSITORY_STRUCTURE.md)
for dependency direction and the compatibility-migration policy.

For a PowerShell-first guide covering setup, tests, evals, Docker, PostgreSQL,
Qdrant, Upstash Redis, AWS deployment/rollback, health checks, load tests, and
GitHub delivery, see [Commands Runbook](docs/COMMANDS_RUNBOOK.md).

## Quick Start

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -e ".[dev]"
```

### 3. Configure environment

Copy `.env.example` to `.env` and update:

- `OPENAI_API_KEY`
- `DATABASE_URL`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `UPSTASH_REDIS_URL`
- `UPSTASH_REDIS_TOKEN`
- `JWT_SECRET`
- `TAVILY_API_KEY` if using web fallback

### 4. Start infrastructure

```powershell
docker compose up -d
```

This starts:

- PostgreSQL
- Qdrant

### 5. Run the API

```powershell
python -m uvicorn app.main:app --reload --port 8003
```

Open:

- `http://localhost:8003/docs`
- `http://localhost:8003/health`

## Main API Endpoints

- `POST /auth/register`
- `POST /auth/login`
- `POST /documents/upload`
- `POST /query`
- `POST /query/sql/execute`
- `GET /admin/health`
- `GET /admin/cache/stats`
- `POST /admin/cache/clear`
- `GET /admin/budgets`
- `GET /admin/rate-limits/{username}`

The same endpoints are also available under the versioned `/api/v1` prefix.

## Example Query Body

```json
{
  "question": "How many P1 incidents breached SLA last month and what is our escalation policy?",
  "top_k": 5,
  "search_mode": "hybrid",
  "enable_rerank": true,
  "enable_hyde": false,
  "enable_crag": true,
  "enable_self_reflective": false
}
```

## Testing

Run the local test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Examples of test coverage:

- auth register/login
- SQL validation
- ingestion duplicate skip
- cache correctness
- hybrid routing
- admin APIs
- eval-smoke behavior

## CI

GitHub Actions is configured to run:

- Ruff linting
- `pytest -q`
- eval-smoke matrix jobs using `python -m evals.runners.run`
- Python dependency auditing with `pip-audit`
- Git-history secret scanning with Gitleaks
- backend container vulnerability scanning with Trivy

Dependabot checks Python packages and GitHub Actions weekly.

The workflow uses current GitHub action versions and is set up for push and pull request validation on `main`.

## Why This Is a Strong Portfolio Project

This project demonstrates more than prompt wiring.

It shows:

- backend architecture for GenAI systems
- safe SQL generation patterns
- hybrid routing design
- retrieval tradeoff awareness
- caching strategy
- guardrails thinking
- admin observability
- evaluation discipline
- CI maturity

That combination is much more compelling to hiring managers than a single-route RAG demo.

## Future Improvements

- admin-triggered real eval runs
- richer cost telemetry
- stronger multi-tenant / department-aware isolation
- automated staging and production promotion pipeline
- Terraform or CDK for reproducible AWS infrastructure
- Alembic migration history and rollback workflows
- OpenTelemetry traces and application-level SLO metrics
- tested RDS, S3, and Qdrant backup restoration
- domain-specific versions for life sciences, regulatory, and scientific knowledge copilots

## License

This project is available under the [MIT License](LICENSE).
