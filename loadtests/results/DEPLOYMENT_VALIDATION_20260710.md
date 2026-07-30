# Deployment Validation - 2026-07-10

## Release

- AWS region: `us-east-2`
- Backend task: `new-adv-rag-backend:31`
- Streamlit task: `new-adv-rag-streamlit:21`
- Image tag: `20260710-hardening1`
- Backend digest: `sha256:fb548f0e9a9103a823bae8a4fd48f26a91b3820fa639f9f83535ed76c5144002`
- Streamlit digest: `sha256:7031f235a416ccb53c6977bfda4e6c46a171f45f3daa2aadc47aaf5fe001f3f8`
- Rollback tasks: backend `:30`, Streamlit `:20`

Both ECS deployments completed with one healthy running task, zero pending tasks, and healthy ALB targets.

## Pre-deployment validation

- Ruff: passed
- Pytest: `70 passed`
- Fixture eval-smoke matrix: passed
- Backend Docker image: built and local `/health` returned `200`
- Streamlit Docker image: built and local page returned `200`

## HTTPS functional validation

- Backend `/health`: `200`
- Streamlit `/_stcore/health`: `200`
- Streamlit page: `200`
- Request ID response header: present
- Six live presets: all returned `200`
- Hybrid and SQL approval flows: passed
- Invalid/stale SQL approval: correctly returned `409`

Preset coverage included Hybrid Default, RAG Policy, SQL Count, Troubleshooting, HyDE Search, and SRAG Reflection.

## Production LLM-scored evaluation

Corpus provenance:

- true documents: `50`
- noisy documents: `324`
- environment: `production-https`
- collection: `new_adv_rag_documents`

Full run:

- completed: `39/40`
- faithfulness: `0.936`
- answer relevancy: `0.905`
- context precision: `0.855`
- context recall: `0.793`
- forbidden violations: `0`
- skipped case: `q-029`, initial ALB `504`

A targeted hybrid SQL+RAG retry completed `8/8`; `q-029` passed with `1.0` for all four metrics. This identifies the initial 504 as transient, while the lower scores on some other mixed cases show that mixed-path retrieval quality still varies.

Local result artifacts:

- `evals/reports/results/20260710_http_all_hardening1.json`
- `evals/reports/results/20260710_http_hybrid_sql_retry_hardening1.json`

## Load validation

### Health

- requests: `56`
- error rate: `0.00%`
- average latency: `63.61ms`
- p95 latency: `77.89ms`
- threshold: pass

### Authenticated RAG

- requests: `19`
- error rate: `0.00%`
- checks: `74/74` passed
- average latency: `5.69s`
- p95 latency: `12.53s`
- functional result: pass
- latency threshold `p95 < 8s`: fail

### Mixed RAG, SQL approval, and hybrid

- requests: `17`
- error rate: `0.00%`
- checks: `32/32` passed
- average latency: `10.44s`
- p95 latency: `31.11s`
- functional result: pass
- latency threshold `p95 < 12s`: fail

Raw k6 files:

- `loadtests/results/health_20260710_201633.txt`
- `loadtests/results/query_rag_20260710_201704.txt`
- `loadtests/results/mixed_smoke_20260710_201809.txt`

## Known warnings

1. Upstash Redis DNS resolution failed from the backend task. The cache correctly failed over to in-memory storage, so requests remained available, but distributed cache behavior is degraded until the configured Upstash endpoint is corrected.
2. RAG and mixed p95 latency exceeded their configured thresholds despite zero HTTP failures.
3. The `backend-alb-response-time-high` alarm ended in `INSUFFICIENT_DATA`; its dimensions and missing-data treatment should be reviewed.
4. The full eval had one transient 504. The affected case passed on immediate targeted retry.

## Final assessment

The release is deployed and functionally healthy. Backend, frontend, all presets, SQL approval, production evals, and load-test response checks work. The remaining release risks are performance, Redis configuration, mixed-path quality variance, and response-time alarm telemetry—not application availability or basic correctness.
