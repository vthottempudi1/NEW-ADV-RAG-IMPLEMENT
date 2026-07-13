# Hybrid Retrieval Hardening - 2026-07-11

> **Historical note updated July 13, 2026:** This document records the original hybrid-route fix.
> The production-candidate release now uses Cloud-v2 sentence-aware chunks, semantic evidence-family
> planning, and `RAG_CACHE_SCHEMA_VERSION = 52`. Schema 15 and the local scores below are historical
> checkpoints, not current release evidence.

## Changes

- Split mixed SQL + RAG questions into a focused document-retrieval question before retrieval.
- Pass the focused question to hybrid search, HyDE, reranking, and CRAG.
- Search a wider candidate pool for operational guidance and multi-entity comparisons.
- Preserve authoritative runbook, policy, Service-discovery, and named-entity sources before reranking truncates candidates.
- Make CRAG retry weak local retrieval even when the first relevance score is below the ambiguous range.
- Add SQL rows to hybrid evaluation context.
- Add `retrieval_question` response metadata for inspection in the API and Streamlit UI.
- Increment the RAG cache schema to `15` so stale pre-fix answers are not reused.
- Preserve Incident Response Runbook and On-Call Escalation Policy subjects across follow-up questions.

## Original mixed-route regression

Before the fix, MTTR and P2-alert questions retrieved unrelated research, ClearCase, Git, AMD, and academic PDFs. SQL results remained correct, but the document guidance was missing or generic.

After the fix, all four original mixed cases retrieve the intended source:

| Case | Focused retrieval source |
|---|---|
| P1 SLA breach + escalation | `oncall-escalation-policy.html` |
| Average MTTR + reduction guidance | `incident-response-runbook.html` |
| Open P2 alerts + first response | `incident-response-runbook.html` |
| Unresolved incidents + remediation | `incident-response-runbook.html` |

No external noisy PDF appeared in these four fixed retrieval sets.

## Targeted mixed-route evaluations

Plain hybrid profile:

| Metric | Score |
|---|---:|
| Faithfulness | `0.875` |
| Context precision | `0.875` |
| Context recall | `0.938` |
| Answer relevancy | `0.900` |
| Completion | `4/4` |

Hybrid + rerank + CRAG profile:

| Metric | Score |
|---|---:|
| Faithfulness | `1.000` |
| Context precision | `0.625` |
| Context recall | `1.000` |
| Answer relevancy | `0.950` |
| Completion | `4/4` |

The lower CRAG-profile context precision is an LLM-judge inconsistency: the recorded contexts contain one correct SQL result and one correct runbook/policy chunk. The individual answers and sources should be reviewed alongside aggregate judge scores.

## New retrieval questions

Twenty-one questions were added: three each for dense, sparse, hybrid, reranking, HyDE, CRAG, and self-RAG. All completed locally with zero forbidden-keyword violations. Every family retrieved its expected primary source after the final source-policy corrections, and no unrelated external noisy PDF remained in the final source sets.

The new-question heuristic scores are useful for regression comparison within the same scorer, but they must not be compared directly with production LLM-scored metrics.

## Follow-up context checks

| Follow-up | Resolved subject | Retrieved source |
|---|---|---|
| “What does it say to do first?” | Incident Response Runbook | `incident-response-runbook.html` |
| “What is the first step?” | On-Call Escalation Policy | `oncall-escalation-policy.html` |
| “Would you use that same object for a database password?” | Secret | `concepts__configuration__secret.txt` |

## Verification

- Ruff: passed
- Pytest: `78 passed`
- CI fixture eval matrix: passed
- Backend Docker image: built
- Backend container `/health`: passed
- Local Qdrant: green, `1,179` points
- Local PostgreSQL: seeded for the mixed-route evaluation

## Final Release Status

The original mixed-query decomposition remains part of the current implementation. Later work added
clarification for underspecified questions, exact source gates, CRAG evidence preservation,
authoritative alternatives, claim-level faithfulness checks, and cache-schema invalidation.

Final Qdrant Cloud-v2 evidence:

| Metric | 40-question challenge | 12-question regression |
|---|---:|---:|
| Faithfulness | 0.965 | 0.963 |
| Context precision | 0.992 | 0.965 |
| Context recall | 0.976 | 0.986 |
| Answer relevancy | 0.978 | 0.983 |
| Source precision | 0.975 | 1.000 |
| Source recall | 0.944 | 1.000 |

Both complete runs recorded zero route, forbidden-answer, and forbidden-source violations. See the
[release evaluation summary](../evals/reports/EVALUATION_SUMMARY_20260712.md) for provenance and the
two documented residual cases.
