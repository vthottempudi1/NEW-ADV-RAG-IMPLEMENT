# Production Readiness Audit

Date: July 12, 2026

## Verdict

The repository is a strong production-minded portfolio system, but it is not honest to call
any RAG system perfect or fully production-certified from a single evaluation run. The local
build is functional and substantially better protected against ambiguous and noisy retrieval.
AWS still runs the previously validated release until a new image completes release review.

## Verified Gates

- 167 unit, integration, contract, and frontend-component tests passed after the evaluator,
  clarification, sealed-v4 regression, sealed-v5 contract, and CI changes.
- All five deterministic CI evaluation partitions passed with exact source precision and source
  recall gates set to 1.000.
- Ruff and Git whitespace validation passed.
- The v2 evaluation corpus contains 49 authoritative and 316 noisy sources and uses
  sentence-aware, metadata-rich chunks.
- The main regression reached faithfulness 0.939, context precision 1.000, context recall 0.983,
  answer relevancy 0.983, source precision 0.958, and source recall 1.000.
- Sealed v4 was consumed once with 0.907 faithfulness, perfect context precision/recall, 0.958
  answer relevancy, 1.000 source precision, and 0.950 source recall. Its three strict findings moved
  into regression, and sealed v5 remains checksummed for the next one-time measurement.

- At the earlier ambiguity-hardening checkpoint, 105 unit, integration, contract, and
  frontend-component tests passed.
- Ruff passed across application, evaluation, test, and UI code.
- Ten unseen ambiguous questions produced clarification with no sources or chunks.
- Six live Docker presets passed, including RAG, SQL, hybrid, HyDE, CRAG, and SRAG paths.
- Backend and Streamlit health endpoints returned HTTP 200.
- A 5-VU/10-second health load test completed 50 requests with 0% failures.
- The reranker reuses its cross-encoder within each worker instead of loading model weights per
  request; a regression test enforces that lifecycle.
- Evaluation contracts now fail on wrong routes, forbidden sources, missing expected sources,
  and configured metric thresholds.

## Remaining Production Risks

1. Retrieval quality is distribution-dependent. A 50-signal/324-noise corpus requires a larger
   human-labelled unseen set covering vague, explicit, negative, adversarial, and multi-turn
   questions. Aggregate scores alone are insufficient.
2. Source authority is inferred mostly from corpus naming and relevance. In a regulated system,
   ingestion should persist explicit owner, authority tier, document version, effective date,
   tenant, ACL, and lifecycle metadata, then enforce those fields in Qdrant filters.
3. Web fallback can return third-party sources. Production policy should allowlist trusted
   domains and paths, prefer first-party Kubernetes documentation, and expose fallback
   provenance. A first allowlist is implemented for Kubernetes, Cilium, AWS/EKS, and Argo CD,
   but it still requires ownership review and periodic freshness testing.
4. LLM grading is probabilistic. CRAG needs periodically reviewed human labels, grader-drift
   checks, and deterministic source-policy gates in addition to model scores.
5. The health load test validates availability, not generation capacity. Authenticated RAG,
   SQL, hybrid, cache-hit/miss, and sustained/soak workloads need release-specific budgets.
   The first 21-question live matrix exceeded its 10-minute harness limit before the reranker
   lifecycle fix and must be rerun with per-case deadlines before an AWS release.
6. Disaster recovery, restore drills, multi-AZ behavior, tenant isolation, key rotation, and
   incident response require operational evidence, not only configuration or documentation.
7. Terraform and migration tooling must be the authoritative deployment path. Manual ECS task
   JSON or raw SQL should not be the only reproducibility mechanism.
8. Browser component tests cover rendering logic, but a real-browser Playwright suite should
   verify login, presets, clarification follow-up, source expansion, SQL approval, and errors.

## Release Rule

Do not deploy merely because an average metric improved. A release must pass code tests,
strict route/source evals, a frozen regression dataset, an unseen challenge dataset, Docker
smoke, authenticated load thresholds, frontend browser checks, security scans, and a rollback
check. Store the report and image digest together so hiring managers can verify the evidence.

## Frozen Challenge Evidence

The first 40-question unseen run is retained even though it failed. It exposed two runtime
failures, two wrong routes, one forbidden-source result, and source precision 0.768. Development
fixes were limited to `q-101` through `q-128`; `q-129` through `q-140` remain the recorded
holdout baseline. This separation is more credible than reporting only the previously tuned
21-question regression suite.
