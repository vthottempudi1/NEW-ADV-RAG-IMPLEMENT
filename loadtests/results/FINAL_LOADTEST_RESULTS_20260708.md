# Final Load Test Results - 2026-07-08

## Scope

- Environment: `aws`
- Base URL: `https://api.aiscientificlabs.com`
- Test user: `test4@example.com`
- Coverage:
  - backend health endpoint
  - authenticated RAG path
  - mixed RAG + SQL approval + hybrid path

## Terminal Commands

```powershell
cd C:\Users\vthot\PORTFOLIO-PROJECTS\ENTERPRISE-ADV-RAG\new-adv-rag-implement

# Health check
.\loadtests\run_k6.ps1 -Script "health.js" -Duration "30s" -Vus "2"

# RAG validation
.\loadtests\run_k6.ps1 -Script "query_rag.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -Vus "2"

# Mixed smoke validation
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -RagVus "1" -SqlVus "1" -HybridVus "1"

# Optional heavier mixed demo run
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "2m" -RagVus "4" -SqlVus "1" -HybridVus "1"
```

## Raw Evidence Files

- `loadtests/results/health_20260708_120849.txt`
- `loadtests/results/query_rag_20260708_121003.txt`
- `loadtests/results/query_rag_20260708_121215.txt`
- `loadtests/results/mixed_smoke_20260708_124436.txt`

## k6 Summary

### Health

- Requests: `58`
- Error rate: `0.00%`
- Average latency: `62.62ms`
- P95 latency: `69.11ms`
- Max latency: `96.76ms`
- Iterations: `58`
- Threshold result: `pass`

### RAG

- First 1-minute run
  - File: `query_rag_20260708_121003.txt`
  - Requests: `19`
  - Error rate: `0.00%`
  - Average latency: `5.59s`
  - P90 latency: `6.28s`
  - P95 latency: `11.53s`
  - Max latency: `14.24s`
  - Iterations: `18`
  - Threshold result: `fail` on `http_req_duration p(95)<8000`

- Second 1-minute run
  - File: `query_rag_20260708_121215.txt`
  - Requests: `22`
  - Error rate: `0.00%`
  - Average latency: `4.78s`
  - P90 latency: `5.09s`
  - P95 latency: `5.14s`
  - Max latency: `6.08s`
  - Iterations: `21`
  - Threshold result: `pass`

### Mixed Smoke

- File: `mixed_smoke_20260708_124436.txt`
- Requests: `16`
- Error rate: `0.00%`
- Average latency: `10.88s`
- P90 latency: `33.55s`
- P95 latency: `34.05s`
- Max latency: `35.43s`
- Iterations: `13`
- Threshold result: `fail` on `http_req_duration p(95)<12000`

## Functional Validation

- Login passed: yes
- `/health` passed: yes
- RAG response shape correct: yes
- Mixed RAG path returned `200`: yes
- SQL approval flow returned `200`: yes
- Mixed SQL final response present: yes
- Mixed hybrid final response present: yes
- HTTP failures observed: no

## CloudWatch and ECS Evidence

- CloudWatch dashboard screenshots captured:
  - top view with manual alarm row and main metrics
  - bottom view with request volume, target health, streamlit CPU, and backend request logs
- Backend ALB response-time spike was visible during both RAG and mixed runs
- Backend ECS CPU movement was visible during both runs
- Backend target group remained healthy during the runs
- Backend request log widget showed recent request lines during the same windows
- ECS backend screenshots captured:
  - service `Active`
  - deployment `Success`
  - `1 running / 0 pending`
  - task health `Healthy`
  - deployment and event history visible

## Final Assessment

- Result: `pass with warnings`
- Main finding: the live backend handled health, authenticated RAG, SQL approval, and hybrid flows without HTTP failures, which is strong functional evidence for the deployed system.
- Secondary finding: latency is the main remaining issue. RAG can pass the configured threshold on repeated runs, but the mixed end-to-end flow still exceeds the current p95 threshold by a wide margin.
- Recommended interpretation for demo/portfolio use: availability and correctness are validated; latency optimization remains the primary next improvement area.

## Next Steps

1. Use this file as the single summary reference for the 2026-07-08 validation session.
2. Keep the raw `.txt` files and screenshots alongside it as source evidence.
3. If needed, rerun `mixed_smoke.js` after cache-warming or backend tuning and compare the new p95 against this baseline.
