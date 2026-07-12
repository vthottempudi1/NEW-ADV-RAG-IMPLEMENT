# Sealed v2 Holdout Protocol

> Status: consumed on 2026-07-12. The immutable result is
> the local raw report timestamp `20260712T161937Z`. This dataset must not be presented as unseen
> again. Development reproductions belong in `sealed_v2_findings_regression.yaml`.

## Scope

`sealed_v2_holdout.yaml` is a 16-question retrieval and grounded-answer
generalization set created after the v2 corpus was built. It does not certify SQL
or combined SQL plus RAG behavior; those require a separately sealed dataset.

## Seal

The expected SHA-256 value is stored in `sealed_v2_holdout.sha256` and enforced by
`tests/contract/test_eval_ci.py`.

## Rules

1. Do not run this dataset while development or regression tuning is in progress.
2. Confirm the intended Git commit, Docker image, collection, and corpus counts.
3. Run it once against that frozen configuration.
4. Archive the raw JSON result even if the strict gate fails.
5. Do not edit questions, goldens, sources, or thresholds after seeing results.
6. Record failures as findings. Fixes must be measured with a newly versioned
   holdout, not by reusing this one as unseen evidence.

## Preflight Seal Check

```powershell
Get-FileHash evals\datasets\sealed_v2_holdout.yaml -Algorithm SHA256
```

Expected hash:

```text
22F1AFD764C1596D6C6101C1C9590393E464BB003BB3E7E6299D333C7EBFF5D6
```

## One-Time Run

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://localhost:8003 `
  --questions evals/datasets/sealed_v2_holdout.yaml `
  --scorer llm `
  --environment docker-v2-sealed `
  --strict `
  --min-faithfulness 0.80 `
  --min-context-precision 0.80 `
  --min-context-recall 0.80 `
  --min-answer-relevancy 0.80 `
  --min-source-precision 0.90 `
  --min-source-recall 0.80 `
  --true-documents 49 `
  --noisy-documents 316
```
