# Load Testing Guide

Run load tests against the **backend API**, not the Streamlit frontend.

Why backend API is the correct target:

- it measures the real system path: auth, routing, cache, OpenAI calls, Qdrant, PostgreSQL, SQL approval flow
- it gives cleaner latency and error signals
- it lines up with ALB, ECS, RDS, and CloudWatch metrics

Use the Streamlit UI only for manual demo validation, not for performance measurement.

Live load tests are intentionally **not** part of GitHub Actions CI.

Reason:

- they hit paid OpenAI-backed endpoints
- they depend on live AWS infrastructure and live data
- they are operational validation, not unit/integration CI

## Prerequisites

Install `k6` on Windows:

```powershell
choco install k6
```

Set credentials for an existing test user:

```powershell
$env:LOADTEST_USERNAME="test4@example.com"; $env:LOADTEST_PASSWORD="test123"
```

Set backend target:

AWS HTTPS backend:

```powershell
$env:BASE_URL="https://api.aiscientificlabs.com"
```

Local backend:

```powershell
$env:BASE_URL="http://localhost:8004"
```

## Safe Run Order

Start cheap and small:

1. `health.js`
2. `query_rag.js`
3. `query_sql.js`
4. `query_hybrid.js`
5. `mixed_smoke.js`

Do not start with high concurrency on `/query`. Those paths can consume OpenAI credits.

## PowerShell Commands

Health:

```powershell
k6 run .\loadtests\health.js
```

RAG:

```powershell
k6 run .\loadtests\query_rag.js
```

SQL:

```powershell
k6 run .\loadtests\query_sql.js
```

Hybrid:

```powershell
k6 run .\loadtests\query_hybrid.js
```

Mixed smoke:

```powershell
k6 run .\loadtests\mixed_smoke.js
```

Wrapper script with saved output:

```powershell
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "2m" -RagVus "4" -SqlVus "1" -HybridVus "1"
```

## Override VUs / Duration

Example:

```powershell
$env:VUS="10"; $env:DURATION="2m"; k6 run .\loadtests\query_rag.js
```

Example mixed run:

```powershell
$env:RAG_VUS="4"; $env:SQL_VUS="1"; $env:HYBRID_VUS="1"; $env:DURATION="2m"; k6 run .\loadtests\mixed_smoke.js
```

## What Each Script Does

`health.js`

- tests `/health`
- no auth required
- cheapest script

`query_rag.js`

- logs in once in `setup()`
- repeatedly calls `/query` with a RAG-style policy question

`query_sql.js`

- logs in once
- calls `/query`
- if `pending_sql` is returned, it automatically approves through `/query/sql/execute`
- later iterations may hit the approved-answer cache

`query_hybrid.js`

- same as SQL flow, but for combined SQL + policy questions

`mixed_smoke.js`

- runs RAG, SQL, and hybrid together with small concurrency
- best script for a short demo of end-to-end backend behavior

## Recommended Demo-Safe Settings

Very safe:

```powershell
$env:VUS="3"; $env:DURATION="1m"; k6 run .\loadtests\query_rag.js
```

Moderate:

```powershell
$env:RAG_VUS="4"; $env:SQL_VUS="1"; $env:HYBRID_VUS="1"; $env:DURATION="2m"; k6 run .\loadtests\mixed_smoke.js
```

## What To Watch In AWS

While the test runs, watch:

- backend ECS CPU
- backend ECS memory
- Streamlit ECS CPU
- ALB 5xx
- ALB target response time
- RDS CPU
- RDS connections

That is the cleanest way to demonstrate autoscaling and alerting behavior.

## Demo Recording Checklist

Use this order while recording:

1. Show `https://api.aiscientificlabs.com/health`
2. Show `https://rag.aiscientificlabs.com`
3. Start one `k6` run from PowerShell
4. Open CloudWatch alarms
5. Open ECS backend service metrics
6. Open ECS Streamlit service metrics
7. Open ALB target response time / 5xx graphs
8. Open RDS CPU and connections
9. Show the saved output file under `loadtests/results/`

## Storing Results

Keep raw output in:

- `loadtests/results/*.txt`

Keep summarized notes in:

- `loadtests/results/*.md`

Start from:

- `loadtests/results/RESULTS_TEMPLATE.md`
