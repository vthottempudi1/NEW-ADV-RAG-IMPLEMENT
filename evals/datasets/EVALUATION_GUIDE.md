# Enterprise RAG Evaluation Guide

This is the single authoritative guide for the project's evaluation datasets, commands, quality
gates, holdout lifecycle, and evidence-retention policy. It is written for new engineers who need
to run the system safely and for hiring managers who want to understand why the reported results
are credible.

Related evidence:

- [`../reports/EVALUATION_SUMMARY_20260712.md`](../reports/EVALUATION_SUMMARY_20260712.md) contains
  curated results and provenance;
- [`../../docs/EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md`](../../docs/EVALUATION_RETRIEVAL_HARDENING_CASE_STUDY_20260711.md)
  explains the bugs, experiments, and engineering decisions;
- [`../../docs/COMMANDS_RUNBOOK.md`](../../docs/COMMANDS_RUNBOOK.md) covers the complete project
  setup, Docker, AWS, database, cache, and load-test commands.

## 1. Evaluation Philosophy

RAG quality cannot be represented by one score or one familiar question. This project evaluates:

- routing correctness;
- retrieval relevance and completeness;
- authoritative source selection;
- resistance to 316 noisy documents;
- grounded answer generation;
- clarification instead of guessing;
- forbidden-answer and forbidden-source behavior;
- SQL and combined SQL+RAG contracts;
- follow-up behavior;
- reproducibility across code, collection, models, and cache schema.

Deterministic checks run on every pull request. LLM-judged metrics run during development,
nightly regression, and release validation because they cost money and can vary between runs.

## 2. Dataset Types and When to Use Them

| Dataset | Purpose | Safe to rerun? | Normal use |
|---|---|---:|---|
| `seed_questions.yaml` | Feature examples and inexpensive smoke checks | Yes | Quick development feedback |
| `regression_suite.yaml` | Primary frozen regression contracts | Yes | Every meaningful retrieval change |
| `challenge_regression_suite.yaml` | Difficult, adversarial, and noisy-corpus cases | Yes | Before release |
| `sealed_v2_findings_regression.yaml` | Defects discovered by consumed sealed v2 | Yes | Historical regression |
| `sealed_v3_findings_regression.yaml` | All consumed sealed-v3 cases | Yes | Historical regression |
| `sealed_v4_findings_regression.yaml` | Three actionable sealed-v4 findings | Yes | Historical regression |
| `sealed_v5_findings_regression.yaml` | Eight actionable sealed-v5 findings | Yes | Current hardening regression |
| `sealed_v2_holdout.yaml` | Historical one-time generalization evidence | No | Preserve only |
| `sealed_v3_holdout.yaml` | Historical one-time generalization evidence | No | Preserve only |
| `sealed_v4_holdout.yaml` | Historical one-time generalization evidence | No | Preserve only |
| `sealed_v5_holdout.yaml` | Historical one-time generalization evidence | No | Preserve only |

The `*.sha256` files protect sealed datasets against accidental editing. Consumed holdouts remain in
Git for auditability, but they are not normal test inputs and must never be presented as unseen
again.

## 3. Current Holdout Registry

| Holdout | Questions | SHA-256 | First valid result | Status |
|---|---:|---|---|---|
| v2 | 16 | `22f1afd764c1596d6c6101c1c9590393e464bb003bb3e7e6299d333c7ebff5d6` | `20260712T161937Z` | Consumed |
| v3 | 12 | `f83c128448441dce7094ff76d68c8bcb436c29e81b0d963ab8250222a3549c9c` | `20260712T191224Z` | Consumed |
| v4 | 12 | `673b7b6d542eb3e353f8a8fe5edaaf07e7dc4140c938c3d79bdefacc7422f4b5` | `20260712T202101Z` | Consumed |
| v5 | 12 | `39da049ff0f5ff6a16565e45b2663334b1a9a49375e2fe720f66f667b9422a15` | `20260712T212502Z` | Consumed |

Do not run any of these four sealed files again. Use the corresponding findings regression.

## 4. Environment Setup

Run commands from the project root:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Configure `.env` with valid OpenAI, PostgreSQL, Qdrant, JWT, and optional Upstash/Tavily values.
For the validated Docker-v2 environment, the important settings are:

```dotenv
QDRANT_COLLECTION=new_adv_rag_documents_v2
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL_ANSWER=gpt-4o
LLM_MODEL_GRADER=gpt-4o-mini
```

Never place credentials in a dataset, report, shell history example, or committed task payload.

## 5. Start and Verify Docker

The Compose backend service is named `app`, not `backend`:

```powershell
docker compose build app
docker compose up -d --force-recreate app
docker compose ps
```

Wait for application startup, then use IPv4 to avoid occasional PowerShell localhost behavior:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health
```

Verify the active cache schema and collection before trusting a regression result:

```powershell
docker compose exec -T app python -c "from app.rag.service import RAG_CACHE_SCHEMA_VERSION; print(RAG_CACHE_SCHEMA_VERSION)"
docker compose exec -T app python -c "from app.config import settings; print(settings.qdrant_collection)"
```

The final July 12 regression used cache schema `48` and collection
`new_adv_rag_documents_v2`.

## 6. Run Static Checks and Automated Tests

```powershell
.\.venv\Scripts\python.exe -m ruff check app evals Eval scripts ui tests
.\.venv\Scripts\python.exe scripts\add_learner_docs.py
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

`add_learner_docs.py` should report zero additions in a committed release candidate. The final
checkpoint contained 172 passing tests; test count is provenance, not a permanent target.

## 7. Run Deterministic Fixture Evaluation

Fixture mode makes no production API calls. It validates runner behavior, routes, forbidden-source
contracts, and exact source gates.

Single partition:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile hybrid `
  --filter hybrid `
  --mode fixture `
  --scorer heuristic `
  --strict `
  --min-source-precision 1.0 `
  --min-source-recall 1.0 `
  --environment local-fixture
```

Run the same five partitions used by CI:

```powershell
$cases = @(
  @{ Profile = "naive"; Filter = "baseline" },
  @{ Profile = "hybrid"; Filter = "hybrid" },
  @{ Profile = "hybrid"; Filter = "hybrid_rag_sql" },
  @{ Profile = "hybrid+rerank+crag"; Filter = "crag" },
  @{ Profile = "naive"; Filter = "clarification" }
)

foreach ($case in $cases) {
  .\.venv\Scripts\python.exe -m evals.runners.run `
    --profile $case.Profile `
    --filter $case.Filter `
    --mode fixture `
    --scorer heuristic `
    --strict `
    --min-source-precision 1.0 `
    --min-source-recall 1.0 `
    --environment local-ci

  if ($LASTEXITCODE -ne 0) {
    throw "Fixture evaluation failed: $($case.Filter)"
  }
}
```

## 8. Run the Main Docker Regression

The evaluator runs from the host virtual environment and calls the Docker backend over HTTP. The
runtime backend image intentionally does not include evaluation datasets.

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://127.0.0.1:8003 `
  --questions evals/datasets/regression_suite.yaml `
  --scorer llm `
  --environment docker-v2-regression `
  --strict `
  --min-faithfulness 0.80 `
  --min-context-precision 0.80 `
  --min-context-recall 0.80 `
  --min-answer-relevancy 0.80 `
  --min-source-precision 0.90 `
  --min-source-recall 0.80
```

LLM evaluation uses paid API calls. A failed strict gate exits nonzero but still writes a report.

## 9. Run the Challenge Regression

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://127.0.0.1:8003 `
  --questions evals/datasets/challenge_regression_suite.yaml `
  --scorer llm `
  --environment docker-v2-challenge `
  --strict `
  --min-faithfulness 0.80 `
  --min-context-precision 0.80 `
  --min-context-recall 0.80 `
  --min-answer-relevancy 0.80 `
  --min-source-precision 0.90 `
  --min-source-recall 0.80
```

## 10. Run Findings Regressions

Run the latest v5 findings regression after retrieval, routing, prompt, evaluator, chunking, or
cache changes:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://127.0.0.1:8003 `
  --questions evals/datasets/sealed_v5_findings_regression.yaml `
  --scorer llm `
  --environment docker-v2-schema48 `
  --strict `
  --min-faithfulness 0.80 `
  --min-context-precision 0.80 `
  --min-context-recall 0.80 `
  --min-answer-relevancy 0.80 `
  --min-source-precision 0.90 `
  --min-source-recall 0.80
```

Run every historical findings suite when changing shared retrieval or evaluator logic:

```powershell
$datasets = @(
  "evals/datasets/sealed_v2_findings_regression.yaml",
  "evals/datasets/sealed_v3_findings_regression.yaml",
  "evals/datasets/sealed_v4_findings_regression.yaml",
  "evals/datasets/sealed_v5_findings_regression.yaml"
)

foreach ($dataset in $datasets) {
  .\.venv\Scripts\python.exe -m evals.runners.run `
    --profile all `
    --mode http `
    --api-base http://127.0.0.1:8003 `
    --questions $dataset `
    --scorer llm `
    --environment docker-v2-all-findings `
    --strict `
    --min-faithfulness 0.80 `
    --min-context-precision 0.80 `
    --min-context-recall 0.80 `
    --min-answer-relevancy 0.80 `
    --min-source-precision 0.90 `
    --min-source-recall 0.80

  if ($LASTEXITCODE -ne 0) {
    throw "Regression failed: $dataset"
  }
}
```

## 11. Target Specific Questions

`--ids` accepts one comma-separated value, not separate positional arguments:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://127.0.0.1:8003 `
  --questions evals/datasets/sealed_v5_findings_regression.yaml `
  --ids q-601,q-606,q-611 `
  --scorer llm `
  --environment docker-targeted
```

Targeted runs are diagnostic. They do not replace the complete strict suite.

## 12. Run Against a Non-Docker Service

Start PostgreSQL and Qdrant, run the backend from the host, then use HTTP mode:

```powershell
docker compose up -d postgres qdrant
.\.venv\Scripts\python.exe scripts\seed_db.py --no-ingest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base http://127.0.0.1:8000 `
  --questions evals/datasets/regression_suite.yaml `
  --scorer llm `
  --environment host-local
```

`--mode local` invokes application services in the evaluator process. Use it for service-level
debugging, not as a substitute for HTTP contract testing.

## 13. Run Against AWS

Use the deployed HTTPS API only after Docker and CI pass:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
  --profile all `
  --mode http `
  --api-base https://api.aiscientificlabs.com `
  --questions evals/datasets/regression_suite.yaml `
  --scorer llm `
  --environment aws-release `
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

Record the Git commit, image digest, ECS task revision, Qdrant collection, cache schema, model names,
and corpus counts with the release evidence.

## 14. Metric Interpretation

| Metric | Question answered |
|---|---|
| Faithfulness | Are answer claims supported by retrieved evidence? |
| Context precision | Are retrieved passages relevant rather than noisy? |
| Context recall | Does the context contain the required answer evidence? |
| Answer relevancy | Does the response answer the actual question? |
| Source precision | How many returned sources belong to an accepted authoritative group? |
| Source recall | How many required source groups were covered? |
| Route violations | Did RAG, SQL, hybrid, or clarification routing violate the contract? |
| Forbidden violations | Did disallowed claims or sources appear? |
| Unsupported claims | How many audited claims lacked validated evidence? |

The default strict thresholds used for live release evaluation are:

```text
faithfulness       >= 0.80
context precision  >= 0.80
context recall     >= 0.80
answer relevancy   >= 0.80
source precision   >= 0.90
source recall      >= 0.80
```

Thresholds apply per question and in aggregate. A strong average must not hide one dangerous
answer. Source-less clarification and valid abstention can make some source metrics non-applicable;
the evaluator records those as `None` rather than inventing a perfect score.

## 15. Authoritative Alternative Sources

Some questions can be answered by more than one authoritative document. Dataset entries may define
`acceptable_source_groups`:

```yaml
acceptable_source_groups:
  - [concepts__overview__components.pdf, tutorials__kubernetes-basics__explore__explore-intro.pdf]
  - [concepts__scheduling-eviction__kube-scheduler.pdf]
```

Each outer group is required. Any source inside one group can satisfy that requirement. This avoids
penalizing valid alternative evidence without allowing unrelated sources. Do not add alternatives
merely to make a failing score pass; verify that each alternative contains the required evidence.

## 16. Cache Safety

If answers are byte-for-byte identical after a retrieval or prompt change, inspect cache behavior.
Every behavior-changing retrieval or synthesis update must advance `RAG_CACHE_SCHEMA_VERSION`.

Verify the running value:

```powershell
docker compose exec -T app python -c "from app.rag.service import RAG_CACHE_SCHEMA_VERSION; print(RAG_CACHE_SCHEMA_VERSION)"
```

Rebuild and recreate the backend after a schema change:

```powershell
docker compose build app
docker compose up -d --force-recreate app
Invoke-RestMethod http://127.0.0.1:8003/health
```

Clearing Upstash is an operational fallback, not a replacement for versioned cache keys.

## 17. Sealed Holdout Lifecycle for a Future Release

Create a new sealed holdout only after a meaningful future product change requires a fresh unbiased
measurement.

1. Develop using reusable regression datasets.
2. Author questions that are absent from all existing datasets.
3. Add complete route, source, answer, and forbidden-behavior contracts.
4. Compute and commit a SHA-256 checksum.
5. Add a contract test for checksum, IDs, completeness, and question uniqueness.
6. Freeze code, Docker image, collection, models, and cache schema.
7. Pass tests, CI, frontend smoke, and load gates.
8. Run the new holdout exactly once.
9. Preserve the first valid result even when it fails.
10. Copy actionable findings into a reusable regression dataset.
11. Never tune and rerun the sealed file while describing it as unseen.

Verify a future checksum without executing questions:

```powershell
$dataset = "evals\datasets\sealed_v6_holdout.yaml"
$checksumFile = "evals\datasets\sealed_v6_holdout.sha256"
$expected = (Get-Content $checksumFile -Raw).Trim().Split()[0].ToLower()
$actual = (Get-FileHash $dataset -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "Sealed holdout checksum mismatch" }
```

An infrastructure failure before any question receives a model answer does not consume a holdout.
A valid run with answers consumes it even if strict gates fail.

## 18. Reports and Git Retention

Raw reports are written under `evals/reports/results/` and intentionally ignored by Git. They can
contain answers, contexts, source names, and quoted document examples and can grow very large.

Keep:

- datasets and regression contracts;
- sealed checksums;
- this guide;
- curated evaluation summaries;
- CI artifacts with appropriate retention and access controls.

Do not commit:

- raw JSON reports;
- credentials or `.env` files;
- generated task definitions containing resolved secrets;
- local cache data;
- copied customer or private source text.

## 19. Troubleshooting

### Connection refused or closed

```powershell
docker compose ps -a
docker compose logs app --tail 200
curl.exe -sS -i http://127.0.0.1:8003/health
```

The application may close an early connection while Uvicorn is still starting. Wait for
`Application startup complete`.

### `--base-url` or `--dataset` is unrecognized

Use the implemented argument names:

```text
--api-base
--questions
```

### Multiple IDs are rejected

Correct:

```text
--ids q-601,q-606,q-611
```

Incorrect:

```text
--ids q-601 q-606 q-611
```

### Results appear unchanged after a fix

Verify the image was rebuilt, the container was recreated, and the cache schema increased. Do not
accept a regression report whose answers came from the previous cache schema.

### Strict gate fails despite a good aggregate

Inspect `per_question_threshold_failures`. Per-question failure is deliberate and must not be
removed merely to obtain a green average.

### Source precision fails on an authoritative alternative

Inspect whether the alternative truly contains the required evidence. If it does, model the
semantics with `acceptable_source_groups`; otherwise fix retrieval.

## 20. What Hiring Managers Should Take Away

The important engineering story is not that every run was perfect. It is that the project:

- tested against a 49-authoritative/316-noisy-source corpus;
- preserved failed unseen results instead of hiding them;
- corrected evaluator bugs that had produced impossible scores;
- separated exact source identity, source precision, and source recall;
- added per-question gates so averages could not conceal failures;
- converted every consumed holdout finding into a regression;
- versioned cache behavior so stale answers could not impersonate new code;
- distinguished genuine retrieval defects from valid authoritative alternatives;
- used deterministic PR gates and probabilistic LLM release metrics appropriately;
- stopped tuning once the accepted regression gates passed.

The final schema-48 v5 findings regression achieved faithfulness `0.975`, context precision
`1.000`, context recall `0.979`, answer relevancy `1.000`, source precision `1.000`, and source
recall `1.000`, with no route or forbidden-source violations. Those numbers are reproducible
regression evidence, not a claim that arbitrary future questions will always be perfect.
