# Evaluation Summary — 2026-07-12

This curated summary is safe to version in Git. Raw JSON reports contain answers, retrieved
contexts, and source names; they remain local or should be retained as access-controlled CI
artifacts rather than committed.

## Valid test configuration

- Qdrant collection: `new_adv_rag_documents_v2`
- Corpus: 49 authoritative sources and 316 noisy sources
- Embeddings: `text-embedding-3-small`
- Answer model: `gpt-4o`
- Grader model: `gpt-4o-mini`

## Main 12-question regression

Valid report timestamp: `20260712T175726Z`

| Metric | Score |
|---|---:|
| Faithfulness | 0.939 |
| Context precision | 1.000 |
| Context recall | 0.983 |
| Answer relevancy | 0.983 |
| Source precision | 0.958 |
| Source recall | 1.000 |

There were no route, forbidden-answer, or forbidden-source violations.

## Sealed v3 one-time result

Valid report timestamp: `20260712T191224Z`. An earlier v3 attempt used the legacy collection and
is excluded as a configuration-error run.

| Metric | Score |
|---|---:|
| Faithfulness | 0.942 |
| Context precision | 1.000 |
| Context recall | 1.000 |
| Answer relevancy | 0.950 |
| Source precision | 0.833 |
| Source recall | 0.800 |

The sealed run exposed one genuine ambiguity-routing defect for “Can you rotate it now?”, plus
source-contract differences where correct answers used a minimum sufficient source or an alternate
authoritative source. The ambiguity defect was moved into regression and fixed.

## Consumed v3 regression after fixes

Valid report timestamp: `20260712T193154Z`.

| Metric | Score |
|---|---:|
| Faithfulness | 0.876 |
| Context precision | 1.000 |
| Context recall | 1.000 |
| Answer relevancy | 1.000 |
| Source precision | 0.958 |
| Source recall | 0.800 |

There were no route or forbidden-source violations. Per-question flags remain for some redundant
golden-source contracts and stochastic claim-judging decisions; aggregate product behavior passes
the release thresholds.

## Deterministic CI policy

Pull requests run tests, lint, security scans, fixture evaluations, route checks, forbidden-source
checks, and exact ID-based source precision/recall gates. LLM-judged metrics remain appropriate for
nightly or release-candidate evaluation because they have API cost and judge variance.

The fixture matrix now enforces source precision and source recall of `1.000` for baseline,
hybrid, hybrid SQL+RAG, CRAG, and clarification partitions. All five jobs passed locally with the
same command used by CI. The complete repository validation also passed with Ruff clean and
`167 passed` in Pytest after the sealed-v4 regression safeguards were added.

## Evaluator and regression safeguards added

The evaluator now distinguishes exact source identity from loose filename similarity, prevents
impossible scores when evidence is absent, treats non-applicable metrics as `None`, checks
claim-level support, and applies configured thresholds per question and in aggregate.

The consumed sealed-v3 findings are preserved in
`evals/datasets/sealed_v3_findings_regression.yaml`.

## Sealed v4 one-time result

Valid report timestamp: `20260712T202101Z`. Provenance: commit `4b94d04`, environment `docker-v2`,
collection `new_adv_rag_documents_v2`, answer model `gpt-4o`, grader `gpt-4o-mini`.

| Metric | Score |
|---|---:|
| Faithfulness | 0.907 |
| Context precision | 1.000 |
| Context recall | 1.000 |
| Answer relevancy | 0.958 |
| Source precision | 1.000 |
| Source recall | 0.950 |

There were no route, forbidden-answer, or forbidden-source violations. Aggregate gates passed,
but strict per-question gates correctly identified q-501 faithfulness, q-505 faithfulness and
answer completeness, and q-507 source completeness. These three cases are now development-only
regressions in `evals/datasets/sealed_v4_findings_regression.yaml`.

Sealed v5 is the new checksummed, unseen one-time holdout. It must remain unexecuted until the v4
regression and complete release gates pass.

## Sealed-v4 findings regression after schema 47

Valid report timestamp: `20260712T205001Z`. The first attempted regression reused schema-46 cache
entries and was rejected as invalid evidence. After advancing `RAG_CACHE_SCHEMA_VERSION` to 47 and
rebuilding Docker, q-501, q-505, and q-507 all passed:

| Metric | Score |
|---|---:|
| Faithfulness | 1.000 |
| Context precision | 1.000 |
| Context recall | 1.000 |
| Answer relevancy | 1.000 |
| Source precision | 1.000 |
| Source recall | 1.000 |

There were zero unsupported claims and no route, forbidden-answer, or forbidden-source violations.
The incident reinforces that every retrieval or synthesis policy change must advance the cache
schema before its evaluation can be considered valid.

## CI failure analysis and repair

The prior GitHub Actions run failed for three independent infrastructure/repository reasons rather
than an application-test failure: generated learner notes were not committed, Gitleaks scanned
public example credentials inside retired raw-report history, and Trivy exhausted runner disk while
exporting the ML container. The repair materializes learner notes, narrowly allowlists only the
retired `evals/reports/results/*.json` history, reclaims unused hosted-runner toolchains before the
container build, and limits Trivy to vulnerability scanning. Local verification passed the exact
historical Gitleaks range, Ruff, 167 tests, and all five deterministic CI eval partitions.

## Report retention

Raw result JSON is ignored by Git because it contains generated answers, retrieved contexts, and
source details and grows rapidly. CI may upload raw reports as access-controlled, short-lived
artifacts. This curated summary is the version-controlled evidence for reviewers.
