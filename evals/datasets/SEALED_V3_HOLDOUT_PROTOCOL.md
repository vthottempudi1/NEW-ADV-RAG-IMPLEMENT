# Sealed v3 Holdout Protocol

`sealed_v3_holdout.yaml` is the next one-time generalization test. It was created after sealed v2
was consumed and before fixes based on the v2 findings. It must not be executed during development.

## Development inputs

- Use `sealed_v2_findings_regression.yaml` to reproduce and fix v2 findings.
- Preserve `sealed_v2_holdout.yaml`, its checksum, and result
  `evals/reports/results/20260712T161937Z_all.json` as historical evidence.
- Do not alter v3 questions, sources, answers, or thresholds after calculating its checksum.

## Release procedure

1. Pass all development and regression suites.
2. Commit the application, evaluator, datasets, Docker configuration, and documentation.
3. Record the commit hash, image identity, Qdrant collection, corpus counts, and model versions.
4. Verify the v3 checksum.
5. Run v3 exactly once and archive its raw report regardless of outcome.
6. Never tune against v3 while continuing to call it unseen.

The one-time command should be issued only after the release candidate is frozen.

## Seal

Expected SHA-256:

```text
F83C128448441DCE7094FF76D68C8BCB436C29E81B0D963AB8250222A3549C9C
```

Verify without executing the dataset:

```powershell
$expected = (Get-Content evals\datasets\sealed_v3_holdout.sha256 -Raw).Trim().Split()[0]
$actual = (Get-FileHash evals\datasets\sealed_v3_holdout.yaml -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) { throw "Sealed v3 checksum mismatch" }
```

## One-time command after freeze

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://localhost:8003 `
  --questions evals/datasets/sealed_v3_holdout.yaml `
  --scorer llm `
  --environment docker-v3-sealed `
  --strict `
  --min-faithfulness 0.80 `
  --min-context-precision 0.80 `
  --min-context-recall 0.80 `
  --min-answer-relevancy 0.80 `
  --min-source-precision 0.90 `
  --min-source-recall 0.80
```
