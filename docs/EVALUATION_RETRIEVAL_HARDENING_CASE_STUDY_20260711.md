# Evaluation and Retrieval Hardening Case Study

## Purpose

This document records the full July 2026 evaluation-hardening effort for the
Enterprise Advanced RAG project. It is intentionally more detailed than the main
README or project writeup. The goal is to show hiring managers and future
maintainers how evaluation results were challenged, reproduced, corrected, and
used to improve the system.

This is not a claim that every intermediate score represented production quality.
Several runs exposed evaluator defects, cached-state problems, weak retrieval, and
incomplete answers. Failed experiments are included because identifying and
reverting them was part of the engineering work.

## Starting Point

The project already supported dense, sparse, and hybrid retrieval, reranking,
HyDE, CRAG, self-reflective RAG, SQL routing, combined SQL plus RAG answers,
Docker, AWS ECS, Qdrant, PostgreSQL, Redis-compatible caching, and a Streamlit UI.

The original evaluation presentation had three weaknesses:

1. Old and new result files were being discussed together.
2. Aggregate metrics could hide individual broken questions.
3. Some scores measured evaluator behavior rather than application behavior.

An early example quoted hybrid-plus-rerank precision `0.304` and recall `0.223`,
and hybrid-plus-rerank-plus-CRAG precision `0.623`, recall `0.734`, and
faithfulness `0.543`. Those figures were not accepted as current production
evidence because their provenance did not match the latest stabilized HTTPS run.
This led to the first rule of the remediation: evaluate only timestamped current
artifacts with explicit environment and corpus provenance.

## Phase 1: Establishing the Real Corpus and Runtime State

The working assumption was a noisy corpus containing 50 authoritative documents
and 324 noisy documents. Later auditing showed why a verbal ingestion count is not
enough:

- the AWS Qdrant collection contained 33,113 points;
- it exposed 366 unique source names;
- 365 sources were reproducible from the local seed corpus;
- those local sources resolved to 49 authoritative and 316 noisy files;
- one additional source was a runtime deployment test upload;
- Qdrant payloads contained only `source` and `text`, so original upload attempts
  could not be reconstructed exactly.

This distinction matters. “Files attempted,” “files reported as successfully
ingested,” “unique source names,” and “documents reproducible from source control”
are different measurements.

The local Docker and AWS paths were also verified separately:

- local Docker used the local Compose Qdrant service;
- AWS ECS backend revision 36 used Qdrant Cloud;
- the ECS backend was running and healthy;
- no recent Qdrant connection errors were found;
- local and AWS collections were separate and could not be treated as one state.

## Phase 2: Cache Failure and Mixed SQL plus RAG Instability

Some combined SQL plus RAG answers became inconsistent after previously working.
Investigation found that the free Upstash Redis capacity had been exhausted and
the Redis REST URL had changed. The cache was cleared and connectivity was
restored.

This explained some variability, but it did not explain every retrieval failure.
The important lesson was not to blame all quality regressions on cache state.
After cache recovery, fresh questions still exposed noisy evidence selection and
incomplete synthesis.

The combined route also had evaluation-specific problems:

- document evidence was judged against the entire SQL-plus-document question;
- SQL result rows were packaged differently across local and HTTP evaluation;
- document chunks were penalized for not containing database values;
- the retrieval subquestion used by evaluation could differ from production;
- follow-up wording could lose the original policy context.

The fixes aligned evaluation with production behavior:

- hybrid questions are decomposed into quantitative and documentation clauses;
- document evidence is scored against the RAG clause;
- database evidence is scored against the SQL clause;
- SQL rows are represented as typed database evidence;
- retrieval metadata records the focused retrieval question;
- follow-up context preserves the relevant operational subject.

One focused combined-path checkpoint reported:

| Metric | Score |
|---|---:|
| Faithfulness | 1.000 |
| Context recall | 1.000 |
| Answer relevancy | 0.950 |
| Forbidden violations | 0 |

Context precision was initially absent from that output. That omission triggered
additional work instead of being silently interpreted as a perfect result.

## Phase 3: Moving Beyond Known Questions

The question “How do I scale?” exposed a major generalization problem. Auto mode
selected hybrid plus reranking plus CRAG, assigned a high CRAG relevance score,
but returned a mixture of Kubernetes sources and unrelated research documents.
The noisy sources included general web-architecture, probability, and language
model papers.

This showed that known-question evaluation was insufficient. A system can score
well on familiar questions while failing on short, ambiguous, or previously
unseen wording.

The response was to build broader evaluation datasets:

- a 21-question live retrieval matrix;
- `evals/datasets/challenge_regression_suite.yaml` (formerly the unseen challenge set; now consumed);
- a frozen final holdout;
- route, forbidden-source, and expected-source contracts;
- clarification and abstention cases;
- multi-document evidence questions;
- adversarial source-authority questions.

The challenge dataset included golden answers and expected sources. This corrected
an earlier limitation where questions without meaningful golden answers could
produce impressive-looking but weakly grounded scores.

Dataset counts also caused confusion during the work. The challenge file contained
40 questions, but one tuning command intentionally selected only 28. The remaining
12 were reserved as an untouched holdout. This was not a missing-data defect; it
was a partitioning decision that needed to be made explicit in commands and
reports. Warnings such as `No golden entries for features` were reviewed rather
than suppressed: they indicated that a selected dataset did not cover every
profile family, which can be acceptable for a focused holdout but must not be
described as full feature coverage.

## Phase 4: Discovering That Perfect Scores Could Be Wrong

Several evaluation runs produced `1.000` values. These were not accepted at face
value. Manual inspection found impossible or misleading cases:

- empty contexts could receive perfect context recall;
- generic filename token overlap could count the wrong source as correct;
- one relevant source could hide missing evidence from another required source;
- aggregate averages could hide a zero-scoring question;
- LLM graders sometimes answered using their own knowledge rather than retrieved
  context;
- faithfulness graders could approve claims without auditable evidence.

The evaluator was hardened with deterministic guards:

- context recall is zero when no context exists, except for a separately
  recognized correct abstention outcome;
- source matching uses normalized complete source identities rather than generic
  token fragments;
- source recall is measured separately from source precision;
- impossible-score guards prevent empty evidence from receiving retrieval credit;
- route and forbidden-source checks remain independent of LLM grading;
- result JSON includes provenance and threshold failures.

This changed the meaning of a high score: it had to survive both LLM judgment and
deterministic integrity checks.

## Phase 5: Holdout Results and Honest Interpretation

One 21-question-style evaluation checkpoint reported:

| Metric | Score |
|---|---:|
| Source precision | 1.000 |
| Context recall | 0.889 |
| Answer relevancy | 0.755 |
| Context precision | 0.558 |
| Heuristic faithfulness | 0.561 |

This was not presented as production-ready. Source selection was strong, but the
retrieved passages and generated answers were not consistently complete or
grounded.

The final untouched holdout then went through multiple iterations. Representative
artifacts include:

- `20260712T005617Z_all.json`;
- `20260712T010159Z_all.json`;
- `20260712T010843Z_all.json`;
- `20260712T011624Z_all.json`;
- `20260712T012802Z_all.json`;
- `20260712T013351Z_all.json`;
- `20260712T024853Z_all.json`;
- `20260712T025338Z_all.json`;
- `20260712T031213Z_all.json`;
- `20260712T031802Z_all.json`.

The sequence is important because the runs are not interchangeable. They used
different evaluator logic or application changes.

For example, `20260712T024853Z_all.json` reported:

| Metric | Score |
|---|---:|
| Faithfulness | 0.649 |
| Context precision | 0.833 |
| Source precision | 1.000 |
| Source recall | 0.900 |
| Context recall | 0.875 |
| Answer relevancy | 0.892 |
| Unsupported claims | 17 |

After correcting evaluator defects, `20260712T025338Z_all.json` reported:

| Metric | Score |
|---|---:|
| Faithfulness | 0.900 |
| Context precision | 0.833 |
| Source precision | 1.000 |
| Source recall | 0.900 |
| Context recall | 0.875 |
| Answer relevancy | 0.892 |
| Unsupported claims | 5 |

The improvement did not mean the application suddenly became perfect. It meant
the previous evaluator had falsely classified question-provided scenario facts as
hallucinations and had mishandled source indices.

## Phase 6: Claim-Level Faithfulness Auditing

Faithfulness originally appeared as one opaque number. The evaluator was changed
to produce a claim audit containing:

- the factual claim;
- whether it was supported;
- evidence type;
- source index;
- supporting quote;
- quote-validation result;
- failure reason.

The evaluator now distinguishes two evidence types:

1. Question evidence: scenario facts explicitly supplied by the user, such as a
   workload name or port number.
2. Context evidence: technical behavior or recommendations that must come from a
   retrieved source.

This fixed an important false-negative pattern. A response repeating “payments
Pods,” “GPU nodes,” or “TCP 8443” should not be marked hallucinated when those
facts came from the question. However, the technical claim explaining what
Kubernetes does still requires document evidence.

Retrieved contexts were explicitly numbered for grading. When the grader selected
the wrong source index but supplied a quote that existed in another retrieved
source, the evaluator corrected the index instead of penalizing the application.
Invented or absent quotes still failed.

Correct no-evidence abstentions were also separated from retrieval failure. A
question asking for the exact cause of yesterday's outage should receive full
safety credit when the indexed corpus contains no audit log or incident timeline
and the system refuses to speculate.

## Phase 7: Retrieval Completeness and Source Authority

Multi-document questions exposed a different weakness: the correct source family
could be found, but the selected passage might cover only one part of the answer.

Evidence plans were added for composite Kubernetes questions, including:

- Ingress, Service routing, and readiness probes;
- ConfigMap mounted-volume propagation and environment-variable restart behavior;
- NetworkPolicy selection, ingress/egress isolation, additive policy semantics,
  and plugin enforcement;
- scheduler filtering, scoring, highest-ranked-node selection, and binding;
- Secret, ServiceAccount, and RBAC evidence;
- DaemonSet placement restrictions.

The planner can retain several complementary chunks from the same authoritative
document. Previously, filename-family deduplication could collapse three required
NetworkPolicy passages into a single chunk.

Non-Kubernetes research documents are removed when authoritative Kubernetes
sources are available. User instructions to treat an unrelated probability PDF
as Kubernetes authority are ignored, while the response continues using the
appropriate scheduler documentation.

## Phase 8: Hybrid Question Rewrite Bug

A production bug was found in the hybrid question rewriter. Any question
containing the word `policy` could be rewritten as an on-call escalation-policy
question. This was incorrect for NetworkPolicy and other non-incident policy
domains.

The rule was narrowed so escalation rewriting requires incident-domain evidence
such as on-call, incident, P1, P2, SLA, or escalation language. A NetworkPolicy
question now retains its original retrieval intent.

This bug demonstrates why evaluator failures should be traced through the actual
question transformation pipeline rather than dismissed as grader variability.

## Phase 9: Aggregate Gates Were Not Enough

A focused Docker run produced an aggregate that passed while individual questions
still failed. The evaluator therefore added per-question threshold failures.

The strict gate now records failures such as:

```text
q-204: faithfulness below threshold
q-208: context recall below threshold
q-210: context precision below threshold
q-212: source recall below threshold
```

An aggregate score can no longer compensate for a broken critical question.
Correct abstentions receive an explicit `abstention_correct` marker so they do not
fail context metrics that are not applicable.

## Phase 10: Failed Generation Experiment and Reversion

A concise composite-generation instruction was tested to reduce unsupported
claims. It made the results worse. One focused run reported aggregate
faithfulness `0.577` even though source precision and source recall were both
`1.000`.

The instruction was reverted. This is a useful engineering result:

- better retrieval does not guarantee faithful generation;
- forcing brevity can remove necessary grounding or cause compressed unsupported
  synthesis;
- prompt changes must be evaluated and reverted when evidence is negative.

The failed score was retained as an artifact rather than hidden.

## Phase 11: Root Cause in Existing Chunks

Manual inspection of retrieved text found damaged boundaries:

```text
ngress exposes HTTP and HTTPS routes...
er assigns a score to each Node...
```

Other chunks ended before the supporting sentence completed. The original
chunker used a fixed 1,000-character window with 100-character overlap. It could
start or end in the middle of a word, sentence, list, or example.

This caused several downstream problems:

- exact supporting quotes were impossible even when the document contained the
  fact;
- reranking evaluated partial statements;
- multi-part answers required reconstructing sentences across chunks;
- the claim auditor correctly rejected reconstructed or paraphrased quotations;
- noisy large PDFs generated hundreds of arbitrary windows.

Sentence-boundary-aware chunking was implemented as the immediate repair. It:

- prefers sentence boundaries near the target chunk size;
- falls back to a word boundary when no sentence boundary is available;
- restarts overlap from a complete sentence when possible;
- prevents mid-word chunk starts and endings;
- retains deterministic chunk identities based on source and text.

Automated tests verify that long text produces chunks that start and end on
sentence boundaries and stay under the configured size.

Sentence-aware chunking is not the final possible design. More advanced options
include:

- token-bounded chunks;
- Markdown or HTML heading-aware chunks;
- paragraph and list preservation;
- table-aware extraction;
- YAML and code-block preservation;
- parent-child retrieval;
- semantic breakpoint chunking;
- document-type-specific chunking.

The selected repair improved the most damaging behavior without introducing a
large new parsing framework. Structure-aware and token-aware chunking remain
reasonable future improvements.

## Phase 12: Why Re-Ingestion Was Required

Changing the chunker does not modify points already stored in Qdrant. Existing
vectors still represent the old damaged text boundaries. Therefore the corpus had
to be parsed, chunked, embedded, and indexed again into a separate v2 collection.

The migration was designed as blue/green rather than destructive:

- preserve the current collection;
- build `new_adv_rag_documents_v2` separately;
- ingest from a verified manifest;
- validate source counts, metadata, retrieval, answers, and UI behavior;
- switch only after the new collection passes;
- retain the old collection for rollback.

Manifest-driven ingestion ensures the same source files are selected every time.
Metadata-rich v2 chunks store:

- document ID;
- content hash;
- authority tier;
- chunk index and total chunks;
- page number when available;
- source path;
- ingestion version.

This work also exposed two operational bugs:

1. Direct execution of `seed_db.py` could import an older installed `app` package
   instead of the repository package. The repository root is now pinned before
   application imports.
2. Document deduplication was collection-agnostic. Old collection metadata could
   cause documents absent from v2 to be skipped. Deduplication now requires the
   same collection and ingestion version.

Large PDFs caused process memory accumulation during the long ingestion job.
Per-document garbage collection was added, and the workflow is resumable without
wiping already indexed v2 points.

## Verification Performed

Verification during the hardening effort included:

- Ruff linting;
- complete Pytest runs, reaching 138 passing tests at the v2 implementation
  checkpoint;
- focused evaluator and ingestion regression suites after later fixes;
- Docker backend rebuilds;
- backend health checks;
- Streamlit preset checks during the broader deployment effort;
- local and deployed HTTP evaluations;
- source and chunk inspection;
- Qdrant collection health and point audits;
- ECS service/task-definition inspection;
- CloudWatch log review for Qdrant errors.

The test count changed as new regression cases were added. A higher test count is
not itself the quality claim; the important point is that each discovered bug
received a targeted regression test.

## Current Honest Status

Completed:

- exact source matching and source recall;
- empty-context and impossible-score guards;
- claim-level faithfulness audit;
- question-premise versus context-evidence distinction;
- abstention-aware scoring;
- atomic context-recall grading;
- per-question strict thresholds;
- hybrid policy rewrite correction;
- multi-passage evidence planning;
- sentence-boundary-aware chunking;
- manifest-driven v2 ingestion;
- metadata-rich Qdrant payloads;
- collection-aware and ingestion-version-aware deduplication;
- resumable local v2 ingestion.

Still required before claiming final production quality:

- finish local v2 ingestion;
- audit v2 source, authority-tier, and metadata counts;
- point Docker backend at v2;
- rerun the untouched holdout without tuning against its answers;
- run the full challenge dataset;
- test frontend presets and new follow-up questions;
- inspect claim-audit failures manually;
- compare latency and embedding/storage cost;
- repeat the blue/green process in Qdrant Cloud;
- deploy and verify AWS before switching production traffic.

## Engineering Lessons

1. A perfect metric can be an evaluator bug.
2. Aggregate scores must not hide per-question failures.
3. Source precision and source recall answer different questions.
4. Correct filenames do not guarantee correct passages.
5. Question-provided facts are not hallucinations.
6. Correct abstention is a successful outcome.
7. Cache recovery does not prove retrieval quality.
8. Known-question success does not prove generalization.
9. Prompt experiments require measured rollback criteria.
10. Chunk quality affects retrieval, reranking, generation, and evaluation.
11. Re-ingestion is mandatory after chunk-boundary changes.
12. Corpus composition must be exported and reproducible, not remembered.
13. Deduplication must be scoped to collection and ingestion schema.
14. A production migration should build a new collection and preserve rollback.

## How to Present This to Hiring Managers

A concise explanation is:

> I did not stop when the RAG evaluation showed high aggregate scores. I built an
> unseen holdout, inspected retrieved chunks and claim-level evidence, found
> impossible evaluator scores, corrected source and context metrics, added
> per-question gates, fixed a production query-rewrite bug, and traced remaining
> faithfulness failures to character-window chunking. I then implemented
> sentence-aware, metadata-rich, manifest-driven ingestion into a blue/green v2
> Qdrant collection so the improvement could be validated without destroying the
> working deployment.

That account is stronger than presenting a single perfect score because it shows
debugging discipline, evaluation integrity, rollback behavior, and production
migration awareness.

## Phase 13: V2 Validation, Sealed Holdouts, and CI Closure (July 12, 2026)

The v2 collection completed with 49 authoritative and 316 noisy sources. Validation used
`new_adv_rag_documents_v2`, `text-embedding-3-small`, `gpt-4o` for answers, and `gpt-4o-mini`
for judging. The source audit found 366 unique source names, no payloads missing `source`, and no
duplicate chunk text within an audited source.

The main 12-question regression reached faithfulness 0.939, context precision 1.000, context
recall 0.983, answer relevancy 0.983, source precision 0.958, and source recall 1.000. The one-time
sealed-v3 run reached 0.942, 1.000, 1.000, 0.950, 0.833, and 0.800 respectively. Its lower source
metrics exposed an ambiguous follow-up and golden contracts that sometimes demanded more sources
than a minimum sufficient answer needed.

The genuine `Can you rotate it now?` defect became a development regression. Generalized
rotate/revoke language now asks for clarification when its object cannot be resolved. The consumed
v3 regression subsequently reached faithfulness 0.876, perfect context and answer-relevancy
aggregates, source precision 0.958, and source recall 0.800. These are strong regression results,
not a claim of universal perfection.

Evaluation governance now requires deterministic source precision and recall of 1.000 in PR CI,
keeps LLM judging for nightly or release runs, moves sealed findings into named regressions, and
retains raw JSON locally or as controlled CI artifacts. Sealed v4 was later consumed once and
reached faithfulness 0.907, context precision/recall 1.000, answer relevancy 0.958, source precision
1.000, and source recall 0.950. Its three strict per-question findings became a named development
regression. Sealed v5 was subsequently consumed once; its findings became an eight-case development
regression covering restoration ambiguity, RBAC evidence, claim discipline, and authoritative
source alternatives.

Final local verification passed all five deterministic CI partitions, Ruff, Git whitespace
validation, and 172 automated tests after the sealed-v5 regression safeguards. The schema-48 v5
regression passed all strict gates with faithfulness 0.975, context precision 1.000, context recall
0.979, answer relevancy 1.000, and source precision/recall 1.000.
