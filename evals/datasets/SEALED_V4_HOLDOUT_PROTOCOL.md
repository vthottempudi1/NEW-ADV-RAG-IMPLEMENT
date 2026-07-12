# Sealed v4 Holdout Protocol

`sealed_v4_holdout.yaml` contains 12 new one-time generalization questions created after sealed v3
was consumed. Do not run or edit v4 during development against `sealed_v3_findings_regression.yaml`.

## Seal

Expected SHA-256:

```text
673B7B6D542EB3E353F8A8FE5EDAAF07E7DC4140C938C3D79BDEFACC7422F4B5
```

## Release sequence

1. Fix and pass the consumed v3 regression suite.
2. Run unit, integration, contract, frontend, and load checks.
3. Commit and record the Git commit and Docker image identity.
4. Confirm the backend and evaluator both use `new_adv_rag_documents_v2`.
5. Verify this checksum and run v4 exactly once.
6. Archive the raw result without tuning or rerunning v4.

The execution command should be prepared only after development is frozen.
