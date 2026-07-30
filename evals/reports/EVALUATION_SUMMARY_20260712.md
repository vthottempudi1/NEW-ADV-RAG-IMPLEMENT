# Enterprise RAG Evaluation Summary — Cloud-v2 Release

**Evaluation period:** July 12–13, 2026

**Release candidate:** Qdrant Cloud v2, retrieval cache schema 52

**Final status:** Strong production-candidate results with two documented retrieval exceptions

This document is the version-controlled evaluation record for the Enterprise Advanced RAG project.
It leads with the final Cloud-v2 evidence, then explains the methodology, fixes, limitations, and
sealed-set history that produced the release.

Raw JSON reports are intentionally excluded from Git because they contain generated answers,
retrieved context, and source details. They may be stored as access-controlled, short-lived CI
artifacts. Commands, dataset responsibilities, and holdout rules are documented in the
[Enterprise RAG Evaluation Guide](../datasets/EVALUATION_GUIDE.md).

---

## Executive Result

The finalized system was evaluated against a Qdrant Cloud collection containing every authoritative
document and more than six times as many noisy distractor documents. The complete challenge and
regression runs both achieved strong aggregate quality with no route, forbidden-answer, or
forbidden-source violations.

| Metric | 40-question challenge | 12-question regression |
|---|---:|---:|
| Faithfulness | **0.965** | **0.963** |
| Context precision | **0.992** | **0.965** |
| Context recall | **0.976** | **0.986** |
| Answer relevancy | **0.978** | **0.983** |
| Source precision | **0.975** | **1.000** |
| Source recall | **0.944** | **1.000** |
| Forbidden-answer violations | **0** | **0** |
| Forbidden-source violations | **0** | **0** |
| Route violations | **0** | **0** |

Reports:

- Challenge: `20260713T074126Z_all.json`
- Regression: `20260713T133920Z_all.json`
- Focused schema-52 closure: `20260713T071620Z_all.json`

The focused closure run scored 1.000 for faithfulness, context precision, context recall, answer
relevancy, source precision, and source recall, with zero unsupported claims. It is targeted closure
evidence, not a claim that all future questions will score perfectly.

---

## Valid Release Configuration

| Component | Release value |
|---|---|
| Environment | `qdrant-cloud-v2-schema52` |
| Qdrant collection | `new_adv_rag_documents_v2` |
| Retrieval cache schema | `52` |
| Embedding model | `text-embedding-3-small` |
| Answer model | `gpt-4o` |
| LLM judge | `gpt-4o-mini` |
| Authoritative sources | 49 |
| Noisy sources | 314 |
| Total sources | 363 |
| Vector points | 34,420 |

The Cloud-v2 audit found:

- zero points missing the `source` field;
- zero duplicate chunks within a source;
- metadata for authority tier, content and document hashes, source path, page number, chunk
  position, total chunks, and ingestion version.

The local manifest contained 49 authoritative and 316 noisy files. Two very large noisy PDFs did
not complete reliably during the 121-minute Cloud ingestion. One left partial points; those points
and the other failed source were removed. The released collection therefore contains 314 noisy
sources. All 49 authoritative sources are present.

---

## What the Metrics Mean

- **Faithfulness** measures whether answer claims are supported by retrieved evidence.
- **Context precision** measures how much retrieved context is useful rather than distracting.
- **Context recall** measures whether the retrieved context covers the evidence needed for the
  expected answer.
- **Answer relevancy** measures whether the response directly answers the question.
- **Source precision** measures whether cited or retrieved source identities are allowed and useful.
- **Source recall** measures whether required authoritative source families were retrieved.

Source precision and context precision are intentionally separate. A correct document may still
contribute an irrelevant chunk, while a relevant-looking chunk from an unapproved source may fail
the source contract.

---

## Evaluation Governance

### Pull-request gates

CI uses deterministic, reproducible checks for:

- expected route;
- forbidden answer patterns;
- forbidden sources;
- exact source identity;
- source precision and source recall;
- fixture-based retrieval partitions.

These checks do not require a judge-model API call and are appropriate for blocking merges.

### Release evaluation

LLM-judged faithfulness, context precision, context recall, and answer relevancy run during broader
regression or release validation. They provide important semantic coverage but have API cost and
probabilistic judge variance. They are not treated as the only definition of correctness.

### Holdout lifecycle

1. Build and checksum a genuinely unseen sealed dataset.
2. Freeze the code, collection, model configuration, and cache schema.
3. Run the sealed set once for an unbiased measurement.
4. Record findings without tuning the sealed score.
5. Move consumed findings into development/regression datasets.
6. Validate fixes with regression and create a new sealed set only for a future release.

A dataset is no longer “unseen” after its results influence an implementation change.

---

## Evaluator Safeguards

The evaluation implementation was hardened after early reports revealed ways a plausible score could
still be wrong. The current evaluator:

- matches exact normalized source identities instead of loose filename similarity;
- supports explicit authoritative alternatives and required source groups;
- rejects impossible positive evidence scores when context is absent;
- represents non-applicable metrics as `None` rather than artificial perfect values;
- checks claim-level evidence support and records unsupported-claim counts;
- enforces thresholds both in aggregate and per question;
- strips adversarial source preferences before answer-relevancy and context-precision judging;
- records environment, collection, models, corpus counts, and cache schema as provenance.

These safeguards prevent high scores caused by evaluator permissiveness rather than system quality.

---

## Retrieval and Ingestion Improvements Validated

### Sentence-aware, metadata-rich v2 ingestion

The Cloud collection was rebuilt using sentence-aware chunk boundaries, controlled overlap,
authority metadata, source and content hashes, chunk position, page provenance, and ingestion
versioning. This reduced broken evidence and made corpus integrity auditable.

Sentence-aware chunking was only one part of the improvement. Retrieval still depends on parser
quality, headings and layout, overlap, embeddings, metadata, reranking, evidence planning, and
grounded synthesis.

### Schema 49–52 retrieval hardening

New challenge questions exposed generalization gaps rather than a missing-corpus problem. The fixes
added semantic evidence-family plans for:

- readiness and startup warm-up;
- stable Service discovery;
- ConfigMap and Secret separation;
- namespace resource policy;
- rolling updates plus readiness;
- StatefulSets with persistent storage;
- scaling and storage adversarial prompts;
- NetworkPolicy paraphrases;
- Deployment versus StatefulSet comparisons;
- Ingress, Service, and readiness composition.

Additional protections ensure that:

- CRAG cannot permanently remove required authoritative evidence supplied by a validated plan;
- a bounded retry can correct an unsupported “the context does not answer” response when direct
  evidence is present;
- narrow deterministic synthesis activates only when the complete authoritative evidence family is
  available;
- equivalent language such as `least-privilege` and `least privilege` maps to the same RBAC plan;
- valid alternative sources are declared explicitly rather than accepted by fuzzy matching;
- cache schema 52 prevents results from older retrieval policies contaminating release evidence.

---

## Documented Release Exceptions

Two cases remain visible rather than being tuned repeatedly against an already-consumed dataset:

1. **`q-106` — memory-pressure eviction**

   Retrieval can occasionally prefer the Pod priority/preemption document over the more specific
   node-pressure eviction source.

2. **`q-126` — rolling-update evidence completeness**

   The answer can correctly explain `maxSurge` and `maxUnavailable` from the Deployment document
   while omitting the second expected API-reference source and adding broader rollout interpretation.

These findings do not invalidate the corpus audit, routing controls, security checks, or strong
aggregate results. They remain named regression targets for a future retrieval-policy release.

Some other per-question LLM metrics varied around their strict threshold even when the sources and
answers were correct. Focused reruns passed those cases. That behavior is recorded as judge variance,
not silently converted into deterministic product success.

---

## Development History

The following consumed sealed sets explain how the final implementation evolved. They are historical
measurements and must not be presented as current unseen evaluation.

| Stage | Report | Primary finding | Outcome |
|---|---|---|---|
| Initial 12-question regression | `20260712T175726Z` | Strong quality; source contracts still evolving | Preserved as regression baseline |
| Sealed v3 | `20260712T191224Z` | Ambiguous “rotate it” query and alternate-source contracts | Clarification routing and source alternatives added |
| Consumed v3 regression | `20260712T193154Z` | Fixes validated; some judge/source-contract variance remained | Findings retained in regression |
| Sealed v4 | `20260712T202101Z` | Three claim/source-completeness cases | Moved to v4 findings regression |
| V4 regression, schema 47 | `20260712T205001Z` | First attempt was invalidated by schema-46 cache reuse | Cache schema advanced; all three cases passed |
| Sealed v5 | `20260712T212502Z` | Clarification, RBAC evidence, unsupported explanation, and alternative-source gaps | Eight findings moved into regression |
| V5 regression, schema 48 | `20260712T231712Z` | Generalized fixes validated | 0.975 faithfulness; all strict per-question gates passed |
| Cloud-v2 schemas 49–52 | July 13 reports | Evidence completeness under noisy, adversarial questions | Final challenge and regression results above |

The schema-47 incident established a permanent rule: every retrieval or synthesis policy change must
advance the answer-cache schema before its evaluation can count as valid evidence.

---

## Repository and CI Verification

The final local checkpoint passed:

- Ruff linting;
- Python compilation;
- learner-documentation enforcement;
- whitespace and diff validation;
- **178 Pytest tests**;
- all deterministic CI evaluation partitions.

GitHub Actions additionally includes dependency auditing with `pip-audit`, Git-history secret
scanning with Gitleaks, and backend-container vulnerability scanning with Trivy.

---

## Final Judgment

The Cloud-v2 results demonstrate strong retrieval, grounding, source discipline, and routing across
a deliberately noisy corpus. They support presenting the project as a production-grade portfolio
implementation and a strong production candidate within its tested scope.

They do not prove universal perfection. The correct release position is:

- the architecture and validation practices are production-minded;
- aggregate retrieval and answer quality are strong;
- deterministic security, route, and source gates are clean;
- two retrieval edge cases remain explicitly documented;
- new product changes should be evaluated with new development tests and, when justified, a newly
  sealed holdout—not by continuing to optimize this consumed distribution.
