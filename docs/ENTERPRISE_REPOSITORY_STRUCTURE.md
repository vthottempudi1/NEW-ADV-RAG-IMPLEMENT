# Enterprise Repository Structure

The repository is organized by deployable boundary, business capability, and test layer.

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
  datasets/        Golden questions and schemas
  runners/         Invokers, profiles, scoring, and CLI
  reports/         Reporting code and retained result artifacts
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

## Compatibility Policy

The old `app.services`, `app.api.<endpoint>`, and uppercase `Eval` paths remain as
thin import bridges for one migration window. New code and CI use only canonical
paths. This avoids breaking existing consumers while preventing new architectural debt.

## Dependency Direction

API and UI layers may call domain packages. Domain packages may depend on core
models, security utilities, storage ports, and observability helpers. Storage and
security packages must not import API or UI code. Evaluation code may invoke public
service boundaries but is never imported by production request handling.
