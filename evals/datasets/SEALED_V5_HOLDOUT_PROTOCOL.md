# Sealed v5 Holdout Protocol

`sealed_v5_holdout.yaml` contains 12 one-time generalization questions created after sealed v4 was
consumed. V5 was consumed by the first valid run `20260712T212502Z_all.json`; do not rerun or edit
it. Its actionable findings live in `sealed_v5_findings_regression.yaml`, whose schema-48 regression
result is `20260712T231712Z_all.json`.

## Seal

Expected SHA-256:

```text
39DA049FF0F5FF6A16565E45B2663334B1A9A49375E2FE720F66F667B9422A15
```

## Release sequence

The procedure was completed: v4 findings passed, the code and runtime were frozen, the checksum was
verified, and v5 ran once. Future development uses the findings regression, never the sealed file.
A later unbiased measurement requires a newly authored and checksummed holdout.

An infrastructure/configuration failure before questions execute does not consume the set. A valid
run with model answers does consume it even if the strict gate fails.
