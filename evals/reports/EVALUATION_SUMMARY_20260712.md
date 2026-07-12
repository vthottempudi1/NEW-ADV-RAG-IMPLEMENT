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
