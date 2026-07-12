# Sealed v5 Holdout Protocol

`sealed_v5_holdout.yaml` contains 12 new one-time generalization questions created after sealed v4
was consumed. Do not run or edit v5 during development against
`sealed_v4_findings_regression.yaml`.

## Seal

Expected SHA-256:

```text
39DA049FF0F5FF6A16565E45B2663334B1A9A49375E2FE720F66F667B9422A15
```

## Release sequence

1. Rebuild Docker with the v4 development fixes.
2. Pass the v4 findings regression, complete tests, deterministic CI gates, frontend smoke, and
   required load checks.
3. Commit and record the Git commit, Docker image identity, Qdrant collection, and model names.
4. Verify the checksum without opening or modifying the dataset.
5. Run v5 exactly once using the command supplied only after development is frozen.
6. Archive the first valid raw report and add only curated metrics to versioned documentation.

An infrastructure/configuration failure before questions execute does not consume the set. A valid
run with model answers does consume it even if the strict gate fails.
