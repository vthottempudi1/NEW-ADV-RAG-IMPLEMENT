# Production Readiness Audit

**Audit date:** July 13, 2026

**Release scope:** Enterprise Advanced RAG, Qdrant Cloud v2, retrieval cache schema 52

## Executive Verdict

The repository is a strong production-grade portfolio implementation and a credible production
candidate within its tested scope. It demonstrates substantially more engineering maturity than a
typical RAG demo: governed RAG/SQL/hybrid routing, human-approved SQL execution, nine defensive
guardrail checkpoints, five active cache tiers, metadata-rich ingestion, noisy-corpus evaluation,
AWS deployment assets, security scanning, observability, load tests, and documented recovery policy.

It is not accurate to call the platform universally production-certified or perfect. Full
production operation still requires organization-specific tenant isolation, automated
infrastructure promotion, authoritative database migrations, distributed tracing, proven restore
drills, and release-specific browser and sustained-load evidence.

### Readiness classification

| Area | Status | Judgment |
|---|---|---|
| Core RAG/SQL/hybrid behavior | **Verified** | Strong automated and live evaluation evidence |
| Retrieval and grounding quality | **Verified with exceptions** | Strong Cloud-v2 aggregates; two documented edge cases |
| Security guardrails | **Implemented, partially assured** | Nine checkpoints and CI scans; not a security certification |
| Cache and cost controls | **Verified** | Five active tiers, fallback behavior, schema invalidation |
| Data handling | **Documented and implemented** | S3/Qdrant/PostgreSQL/Redis responsibilities defined; retention requires operator configuration |
| AWS architecture | **Deployed and documented** | ECS, ALB/HTTPS, RDS, S3, Qdrant Cloud, Redis, Secrets Manager, CloudWatch |
| Observability | **Partially verified** | Request logging, admin telemetry, dashboards and alarms; no full distributed tracing |
| Reliability and recovery | **Policy defined, evidence incomplete** | RTO/RPO and recovery procedure exist; restore and regional-failover drills remain |
| CI and supply-chain checks | **Verified** | Tests, deterministic evals, dependency, secret, and image scanning |
| Automated delivery | **Partial** | CI is automated; production promotion remains runbook-driven |
| Infrastructure as code | **Gap** | Terraform is an import-first foundation, not the authoritative deployment path |
| Database migrations | **Gap** | Numbered SQL exists; mature Alembic upgrade/downgrade tracking remains |
| Browser end-to-end testing | **Partial** | Streamlit component coverage exists; full Playwright workflow remains |

---

## Verified Release Evidence

### Repository quality gates

The final local checkpoint passed:

- **178 Pytest tests** across unit, integration, contract, and frontend-component coverage;
- Ruff linting;
- Python compilation;
- learner-documentation enforcement;
- whitespace and repository-diff validation;
- all deterministic CI evaluation partitions.

GitHub Actions also includes:

- Python dependency auditing with `pip-audit`;
- Git-history secret scanning with Gitleaks;
- backend-container vulnerability scanning with Trivy;
- fixture-based route, forbidden-behavior, and exact source-identity gates.

### Cloud-v2 corpus integrity

The audited Qdrant Cloud collection is `new_adv_rag_documents_v2`:

| Corpus property | Verified value |
|---|---:|
| Vector points | 34,420 |
| Unique sources | 363 |
| Authoritative sources | 49 |
| Noisy sources | 314 |
| Points missing `source` | 0 |
| Duplicate chunks within a source | 0 |

The local manifest contained 316 noisy files. Two very large noisy PDFs did not complete reliably
during Cloud ingestion, and one left partial points. Both failed sources were removed. Every one of
the 49 authoritative sources is present, so the released Cloud corpus deliberately contains 314
noisy distractors rather than claiming 316 successful noisy documents.

The v2 ingestion path uses sentence-aware boundaries and records authority tier, content/document
hashes, source path, page number, chunk position, total chunks, and ingestion version. Corpus
integrity is verified from Qdrant payloads rather than inferred from cache entries or ingestion logs.

### Final evaluation results

Both complete runs used environment `qdrant-cloud-v2-schema52`, Qdrant Cloud v2, `gpt-4o` for
answers, and `gpt-4o-mini` for LLM judging.

| Metric | 40-question challenge | 12-question regression |
|---|---:|---:|
| Faithfulness | **0.965** | **0.963** |
| Context precision | **0.992** | **0.965** |
| Context recall | **0.976** | **0.986** |
| Answer relevancy | **0.978** | **0.983** |
| Source precision | **0.975** | **1.000** |
| Source recall | **0.944** | **1.000** |
| Forbidden-answer violations | **0** | **0** |
| Forbidden-source violations | **0** | **0** |
| Route violations | **0** | **0** |

Evidence reports:

- Challenge: `20260713T074126Z_all.json`
- Regression: `20260713T133920Z_all.json`
- Focused schema-52 closure: `20260713T071620Z_all.json`

The focused closure report scored 1.000 across faithfulness, context precision/recall, answer
relevancy, and source precision/recall, with zero unsupported claims. That targeted result is closure
evidence, not proof that every future question will be perfect.

### Documented evaluation exceptions

Two residual cases remain explicit:

1. `q-106` can prefer a Pod priority/preemption source over the more specific node-pressure
   eviction source for a memory-pressure question.
2. `q-126` can correctly explain `maxSurge` and `maxUnavailable` while omitting a second expected
   API-reference source and adding broader rollout interpretation.

They are accepted release exceptions and future regression targets. The already-consumed challenge
distribution should not be tuned repeatedly to manufacture a perfect report.

The full methodology, sealed-set history, evaluator safeguards, and report-retention policy are in
the [Cloud-v2 evaluation summary](../evals/reports/EVALUATION_SUMMARY_20260712.md).

---

## Architecture and Application Controls

### Routing and orchestration — verified

The backend separates answer routing from document-retrieval policy:

- RAG for document-grounded questions;
- SQL for structured-data questions;
- hybrid SQL + RAG for combined evidence;
- clarification when the request is too ambiguous to answer safely.

LangGraph manages SQL approval and combined workflows. The deployed product presents the principal
RAG, SQL, and SQL + RAG answer paths; clarification is an internal safety outcome.

### Retrieval — verified with residual risk

Implemented retrieval capabilities include dense, sparse, hybrid, reranking, HyDE, CRAG, and
self-reflective RAG. Auto mode selects a bounded strategy, while manual mode supports diagnosis and
demonstration.

Schema 49–52 added semantic evidence-family planning, authoritative alternatives, CRAG evidence
preservation, bounded evidence-denial correction, and narrow grounded synthesis only when a complete
source family is available. Cache schema 52 prevents answers from older policies contaminating the
release.

Retrieval quality remains distribution-dependent. New domains require new corpus analysis,
authority contracts, development questions, and genuinely unseen release evidence.

### Governed Text-to-SQL — verified within current scope

The SQL path uses schema context, `sqlglot` AST validation, read-only restrictions, bounded query
shapes, and explicit human approval before execution. Stale or missing approval state returns a
conflict instead of executing an unverified query.

Production expansion should add stronger tenant-scoped database roles, query timeouts at the
database boundary, concurrency testing for approval state, and organization-specific audit
retention.

### Nine-layer guardrail pipeline — implemented, not certified

The application implements:

1. typed request/model validation;
2. JWT authentication;
3. per-user rate limiting;
4. token-budget enforcement;
5. input restructuring and size control;
6. prompt-injection and unsafe-input pattern checks;
7. moderation and lightweight PII redaction;
8. hardened prompting and untrusted-context isolation;
9. output validation.

SQL AST validation and human approval add a separate trust boundary for database operations.

The prompt-injection, redaction, and output checks are practical baselines, not guarantees against
arbitrary hostile input. Higher-risk deployments need stronger classifiers or policy engines,
adversarial security testing, tenant-aware authorization, and formal threat-model review.

### Five active cache tiers — verified

The active query-time tiers are RAG answers, SQL generation, SQL results, approved SQL/hybrid
answers, and embeddings. Cache-hit metadata exposes estimated avoided LLM and infrastructure cost.

Upstash failure falls back in process; cache availability must affect latency and cost, not answer
correctness. Query cache state is separate from ingestion identity and cannot prove that vectors
exist. Retrieval or synthesis policy changes must increment the cache schema before evaluation.

---

## Data Handling and Storage

The implemented storage responsibilities are:

- **Amazon S3:** uploaded source-document storage in AWS;
- **Qdrant Cloud:** derived chunks, embeddings, and retrieval metadata;
- **PostgreSQL/RDS:** users and structured application data;
- **Upstash Redis:** cached answers, SQL artifacts, embeddings, and rate-limit state;
- **CloudWatch:** application and infrastructure logs/metrics.

AWS Secrets Manager supplies deployed credentials. Local `.env` files are development-only and
excluded from Git.

The [data-handling policy](DATA_HANDLING.md) correctly states that embeddings, caches, SQL results,
logs, and evaluation artifacts may contain sensitive information. It also defines complete deletion
as removal of the original object, derived chunks/embeddings, caches, and applicable traces.

Remaining operational requirements:

- configure and verify S3 versioning, lifecycle, encryption, and access logging;
- set explicit CloudWatch, Redis, database-backup, Qdrant-snapshot, and evaluation retention;
- test complete deletion across every derived store;
- do not ingest regulated or customer-confidential data without approved legal, security, and
  retention controls.

---

## AWS Deployment and Operations

The documented AWS architecture includes:

- ECS Fargate backend and Streamlit services;
- Application Load Balancers, Route 53, and ACM-managed HTTPS;
- RDS PostgreSQL;
- Amazon S3 document storage;
- Qdrant Cloud vectors;
- Upstash Redis caching;
- AWS Secrets Manager;
- CloudWatch log groups, dashboard, alarms, and ECS autoscaling controls.

The deployment runbook covers image builds, ECR pushes, task registration, service rollout, health,
authentication, uploads, presets, query paths, CloudWatch, load tests, and common failure recovery.

This audit does not infer that every local code change is already running on ECS. An AWS release is
valid only when the image digest, task-definition revision, Qdrant collection, cache schema, health
checks, and post-deployment smoke evidence identify the same build.

### Observability — partially verified

Implemented evidence includes request IDs, request duration/status logging, admin health/runtime,
cache, budget and rate-limit endpoints, CloudWatch logs, a dashboard, alarms, and saved-cost
metadata.

Remaining work includes OpenTelemetry-compatible distributed traces, application-owned metric
emission for retrieval/LLM stages, SLO burn-rate alerting, trace correlation across backend and
external services, and documented notification ownership.

### Reliability and recovery — policy present, drills incomplete

The reliability policy defines a portfolio target RTO of four hours and target RPO of 24 hours for
PostgreSQL and uploaded documents. It requires RDS backups, S3 versioning/lifecycle, Qdrant
snapshots or vector reconstruction, Redis cache clearing, and restoration validation.

The project does not yet prove:

- a successful end-to-end RDS/S3/Qdrant restoration exercise;
- complete Multi-AZ behavior for the database and vector store;
- regional failover;
- measured achievement of the stated RTO/RPO;
- sustained fault-injection or soak-test recovery.

Backups are not considered valid until a restoration drill succeeds.

### Load and frontend validation — partial release evidence

Existing k6 suites cover health, authenticated RAG, SQL, hybrid, and mixed-smoke workloads. Earlier
AWS validation demonstrated healthy services and successful frontend presets. These artifacts prove
important paths, but they are not a universal capacity certificate for the schema-52 release.

Before higher-scale production use, run release-specific sustained and soak workloads with cache
hit/miss separation, realistic tenant identities, concurrency around SQL approval, explicit latency
budgets, and failure thresholds. A full Playwright suite should verify login, presets,
clarification/follow-up behavior, source expansion, SQL approval, and error recovery in a real
browser.

---

## Remaining Engineering Gaps

### Priority 1 — required before higher-assurance production

1. **Tenant isolation:** enforce tenant IDs in authorization, vector filters, cache namespaces,
   storage keys, SQL policies, and audit records.
2. **Restore evidence:** execute and record RDS, S3, and Qdrant restoration drills.
3. **Authoritative IaC:** make Terraform/CDK the reproducible source of truth instead of relying on
   hand-maintained ECS JSON and runbook commands.
4. **Migration framework:** adopt Alembic with version tracking, forward migrations, rollback
   strategy, and deployment integration.
5. **Automated promotion:** add staging deployment, smoke gates, controlled ECS promotion, and
   automated rollback based on release health.

### Priority 2 — operational maturity

6. Add distributed tracing and application-level SLO metrics.
7. Complete real-browser end-to-end tests.
8. Expand sustained, soak, concurrency, and fault-injection tests.
9. Route alerts to an owned notification and incident-management channel.
10. Test key rotation, full deletion, dependency remediation, and incident-response exercises.

### Priority 3 — future retrieval releases

11. Keep `q-106` and `q-126` as visible regression targets.
12. Add newly curated questions only when product/corpus behavior changes.
13. Create a new sealed holdout for the next release; do not rename consumed data as unseen.
14. Add richer document owner, version, effective-date, tenant, ACL, and lifecycle metadata before
    using the platform for regulated or multi-organization content.

---

## Release Gate

A release should proceed only when all applicable items are recorded against one immutable image
and configuration:

- code tests, lint, documentation, and security scans pass;
- deterministic route, forbidden-behavior, and exact source gates pass;
- frozen regression passes and a new sealed set is used only once when required;
- corpus count, metadata, duplicates, collection, and embedding dimensions are audited;
- cache schema matches the retrieval/synthesis implementation;
- Docker backend, frontend, upload, authentication, RAG, SQL, hybrid, clarification, presets, and
  follow-ups pass;
- authenticated load thresholds pass without confusing expected rate limits with failures;
- AWS task definitions reference the intended immutable image digest;
- health, logs, dashboards, alarms, and notification routing are verified;
- rollback for both application image and Qdrant collection is demonstrated;
- the release evidence records commit, image digest, task revision, collection, models, dataset
  checksum, environment, and exceptions.

## Final Assessment

The project is ready to be presented confidently to hiring managers as an advanced, production-grade
enterprise RAG implementation. Its architecture, tests, Cloud-v2 evaluation, guardrails, caching,
AWS deployment, and operational documentation demonstrate uncommon depth.

For real customer production, readiness remains conditional on the organization completing the
Priority 1 controls and validating the deployment under its own data classification, tenancy,
availability, recovery, scale, and compliance requirements. That qualification strengthens the
project: it separates demonstrated engineering evidence from claims the repository has not yet
proved.
