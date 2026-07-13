# Enterprise Repository Structure

The repository is organized by deployable boundary, business capability, and test layer.

This is the canonical July 2026 layout. New code should extend these boundaries instead of
reintroducing retired compatibility paths.

```text
app/
  api/v1/          Versioned HTTP endpoints
  core/            LangGraph orchestration and shared state
  rag/             Retrieval, reranking, HyDE, CRAG, Self-RAG, vectors, LLMs
  sql/             SQL generation, validation, approval persistence, execution
  security/        Input/output guardrails and token budgets
  caching/         Query and document cache adapters
  ingestion/       Parsing, chunking, embedding, and indexing
  storage/         Local/S3 storage abstractions
  observability/   Cost and operational telemetry
db/
  migrations/      Ordered database changes
  seeds/           Environment-safe seed definitions
tests/
  unit/            Isolated business rules
  integration/     API and service collaboration
  contract/        Response and evaluation contracts
  e2e/             Browser/deployed journeys
  fixtures/        Shared non-secret test assets
evals/
  datasets/        Development, regression, holdout, and schema assets
  runners/         Invokers, profiles, scoring, and CLI
  reports/         Curated summaries; raw JSON stays ignored/controlled
ui/streamlit/      Independent frontend application
infra/
  docker/          Container build definitions
  ecs/             Current task definitions and policies
  cloudwatch/      Dashboard configuration
  terraform/       Import-first IaC migration boundary
scripts/           Operational and maintenance tools
loadtests/         k6 performance and resilience tests
docs/              Architecture, operations, security, and compliance docs
```

## Canonical Import Policy

Evaluation code lives under lowercase `evals`, and versioned HTTP endpoints live
under `app.api.v1`. Retired uppercase `Eval` and unversioned `app.api.<endpoint>`
bridges must not be restored; keeping one canonical path prevents case-sensitive
deployment failures and duplicate-looking modules. The separate `app.services`
bridges remain temporarily for service-layer migration compatibility.

## Dependency Direction

API and UI layers may call domain packages. Domain packages may depend on core
models, security utilities, storage ports, and observability helpers. Storage and
security packages must not import API or UI code. Evaluation code may invoke public
service boundaries but is never imported by production request handling.

## Maturity Boundaries

- `infra/terraform` is an import-first boundary, not yet the authoritative deployment path.
- `db/migrations` contains ordered SQL, not a complete Alembic upgrade/downgrade history.
- `tests/e2e` has frontend-component coverage; full Playwright browser journeys remain future work.
- `app/observability` provides request/cost telemetry; distributed tracing remains a gap.
- Raw evaluation reports are operational artifacts; only curated summaries belong in Git.

Directory names must not be interpreted as proof that these remaining capabilities are complete.
