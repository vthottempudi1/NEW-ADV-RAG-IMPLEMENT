from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from evals.datasets.schema import load_goldens
from evals.reports.reporting import aggregate, print_table
from evals.runners.invokers import (
    FixtureInvoker,
    HttpServiceInvoker,
    ServiceInvoker,
    SkippedIntent,
)
from evals.runners.post_checks import (
    forbidden_keywords_check,
    forbidden_sources_check,
    source_overlap,
    source_precision,
    source_recall,
)
from evals.runners.profiles import PROFILES


# Captures the exact source revision so an evaluation can be reproduced later.
def _git_commit() -> str | None:
    """Support the evaluation and quality-gate framework by performing git commit.

    Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# Records non-secret runtime context so scores can be traced to a corpus and model setup.
def _evaluation_provenance(args, preflight: dict | None) -> dict:
    """Support the evaluation and quality-gate framework by performing evaluation provenance.

    Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    from app.config import settings

    return {
        "git_commit": _git_commit(),
        "environment": args.environment,
        "collection": (preflight or {}).get("collection") or settings.qdrant_collection,
        "true_documents": args.true_documents,
        "noisy_documents": args.noisy_documents,
        "total_points": (preflight or {}).get("total_points"),
        "unique_sources": (preflight or {}).get("unique_sources"),
        "embedding_model": settings.embedding_model,
        "answer_model": settings.llm_model_answer,
        "grader_model": settings.llm_model_grader,
        "ci_run_id": os.getenv("GITHUB_RUN_ID"),
    }


# Note: Encapsulates local corpus preflight so this responsibility can be understood, tested, and changed independently.
def _local_corpus_preflight(goldens) -> dict | None:
    """Support the evaluation and quality-gate framework by performing local corpus preflight.

    Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    try:
        from app.config import settings
        from app.rag.vector_store import get_client
    except Exception as exc:  # noqa: BLE001
        return {"status": "warning", "warnings": [f"preflight_import_failed: {exc}"]}

    try:
        client = get_client()
        offset = None
        source_counts: dict[str, int] = {}
        total_points = 0

        while True:
            results, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                limit=500,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in results:
                source = str(point.payload.get("source", "") or "")
                source_counts[source] = source_counts.get(source, 0) + 1
                total_points += 1
            if offset is None:
                break
    except Exception as exc:  # noqa: BLE001
        return {"status": "warning", "warnings": [f"preflight_query_failed: {exc}"]}

    unique_sources = sorted(source_counts)
    normalized_actual = {
        Path(source).stem.lower(): source for source in unique_sources if source
    }
    golden_file_sources = {
        Path(source).stem.lower()
        for golden in goldens
        for source in golden.golden_sources
        if source not in {"tavily_web", "database query"}
    }

    matched_goldens = {
        golden
        for golden in golden_file_sources
        if any(golden in actual or actual in golden for actual in normalized_actual)
    }

    warnings: list[str] = []
    dummy_sources = [source for source in unique_sources if "dummy" in source.lower()]
    if total_points == 0:
        warnings.append("collection_empty")
    if len(unique_sources) < 10:
        warnings.append(f"very_low_source_count:{len(unique_sources)}")
    if dummy_sources:
        warnings.append(
            "dummy_sources_present:" + ", ".join(dummy_sources[:5])
        )

    coverage_ratio = (
        len(matched_goldens) / len(golden_file_sources)
        if golden_file_sources
        else 1.0
    )
    if coverage_ratio == 0.0 and len(unique_sources) < 10:
        warnings.append(
            f"low_golden_source_coverage:{len(matched_goldens)}/{len(golden_file_sources)}"
        )

    return {
        "status": "ok" if not warnings else "warning",
        "collection": settings.qdrant_collection,
        "total_points": total_points,
        "unique_sources": len(unique_sources),
        "golden_source_coverage": round(coverage_ratio, 3),
        "warnings": warnings,
    }


# Note: Per question threshold failures is part of the evaluation and quality-gate framework.
def _per_question_threshold_failures(
    rows: list[dict],
    thresholds: dict[str, float | None],
) -> dict[str, dict[str, dict[str, float]]]:
    """Return metric failures by question so aggregate averages cannot hide regressions."""
    failures: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        metrics = row.get("ragas_metrics") or {}
        values = {
            "faithfulness": metrics.get("faithfulness"),
            "context_precision": metrics.get("context_precision"),
            "context_recall": metrics.get("context_recall"),
            "answer_relevancy": metrics.get("answer_relevancy"),
            "source_precision": row.get("source_precision"),
            "source_recall": row.get("source_recall"),
        }
        row_failures = {
            metric: {"actual": float(values[metric]), "minimum": float(minimum)}
            for metric, minimum in thresholds.items()
            if minimum is not None
            and values.get(metric) is not None
            and float(values[metric]) < minimum
        }
        if row_failures:
            failures[str(row.get("id", "unknown"))] = row_failures
    return failures


# Aggregate threshold failures is part of the evaluation and quality-gate framework.
def _aggregate_threshold_failures(
    values: dict,
    thresholds: dict[str, float | None],
) -> dict[str, dict[str, float]]:
    """Return aggregate failures while skipping metrics that are not applicable."""
    return {
        metric: {"actual": float(values[metric]), "minimum": float(minimum)}
        for metric, minimum in thresholds.items()
        if minimum is not None
        and metric in values
        and values[metric] is not None
        and float(values[metric]) < minimum
    }


# Orchestrates main, making this function a clear execution boundary for learners and tests.
def main() -> None:
    """Perform main for the evaluation and quality-gate framework.

    Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Run Ragas eval harness")
    ap.add_argument(
        "--profile",
        required=True,
        choices=list(PROFILES.keys()),
        help="Flag profile to evaluate",
    )
    ap.add_argument(
        "--questions",
        default="evals/datasets/seed_questions.yaml",
        help="Path to seed questions YAML",
    )
    ap.add_argument(
        "--filter",
        default=None,
        help="Only run goldens with demonstrates_feature == FILTER (plus baseline)",
    )
    ap.add_argument(
        "--ids",
        default=None,
        help="Optional comma-separated question IDs to run after feature filtering",
    )
    ap.add_argument(
        "--mode",
        default="local",
        choices=["local", "service", "fixture", "http"],
        help="Invocation mode: local/service runs in-process; http hits a deployed API",
    )
    ap.add_argument(
        "--scorer",
        default="llm",
        choices=["llm", "heuristic"],
        help="Metric scoring backend",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: evals/reports/results/<timestamp>_<profile>.json)",
    )
    ap.add_argument(
        "--api-base",
        default=None,
        help="HTTP API base for deployed eval mode, e.g. http://backend-alb... ",
    )
    ap.add_argument(
        "--username",
        default=None,
        help="Username to use for HTTP eval auth; if omitted, a disposable eval user is registered",
    )
    ap.add_argument(
        "--password",
        default="Test123!",
        help="Password to use for HTTP eval auth",
    )
    ap.add_argument(
        "--token",
        default=None,
        help="Bearer token for HTTP eval mode; skips register/login bootstrap when provided",
    )
    ap.add_argument(
        "--approve-sql",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-approve SQL requests in HTTP eval mode",
    )
    ap.add_argument(
        "--environment",
        default=os.getenv("EVAL_ENVIRONMENT", "local"),
        help="Non-secret environment label stored in the result provenance",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on skipped cases, forbidden content/sources, or route mismatches",
    )
    ap.add_argument("--min-faithfulness", type=float, default=None)
    ap.add_argument("--min-context-precision", type=float, default=None)
    ap.add_argument("--min-context-recall", type=float, default=None)
    ap.add_argument("--min-answer-relevancy", type=float, default=None)
    ap.add_argument("--min-source-precision", type=float, default=None)
    ap.add_argument("--min-source-recall", type=float, default=None)
    ap.add_argument(
        "--true-documents",
        type=int,
        default=None,
        help="Confirmed authoritative-document count for the evaluated collection",
    )
    ap.add_argument(
        "--noisy-documents",
        type=int,
        default=None,
        help="Confirmed distractor-document count for the evaluated collection",
    )
    args = ap.parse_args()
    flags = PROFILES[args.profile]
    goldens = load_goldens(args.questions)

    if args.filter:
        goldens = [
            g
            for g in goldens
            if g.demonstrates_feature in (args.filter, "baseline")
        ]
    if args.ids:
        selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        goldens = [g for g in goldens if g.id in selected_ids]

    invoker = None
    mode = "local" if args.mode == "service" else args.mode
    if mode == "local":
        invoker = ServiceInvoker()
    elif mode == "fixture":
        invoker = FixtureInvoker(goldens)
    elif mode == "http":
        if not args.api_base:
            print("--api-base is required when --mode http is used", file=sys.stderr)
            sys.exit(1)
        invoker = HttpServiceInvoker(
            api_base=args.api_base,
            username=args.username,
            password=args.password,
            token=args.token,
            approve_sql=args.approve_sql,
        )
    else:
        print("Unsupported mode.", file=sys.stderr)
        sys.exit(1)

    preflight = _local_corpus_preflight(goldens) if mode == "local" else None
    if preflight and preflight.get("warnings"):
        print("Local corpus preflight warnings:")
        for warning in preflight["warnings"]:
            print(f"  - {warning}")

    try:
        rows: list[dict] = []
        skipped: list[dict] = []

        for g in goldens:
            try:
                resp, chunks = invoker.invoke(g.question, flags, g.intent)
            except SkippedIntent as e:
                skipped.append({"id": g.id, "reason": str(e)})
                continue
            except Exception as e:
                skipped.append({"id": g.id, "reason": f"error: {e}"})
                continue

            rows.append(
                {
                    "id": g.id,
                    "demonstrates_feature": g.demonstrates_feature,
                    "intent": g.intent,
                    "question": g.question,
                    "answer": resp.answer,
                    # Preserve evidence type and provenance for mixed SQL+RAG
                    # scoring.  The text remains unchanged after the label.
                    "contexts": [
                        f"[Evidence source: {c.source}]\n{c.text}" for c in chunks
                    ],
                    "ground_truth": g.golden_answer or ", ".join(g.golden_answer_keywords),
                    "actual_sources": resp.sources,
                    "golden_sources": g.golden_sources,
                    "acceptable_source_groups": g.acceptable_source_groups,
                    "forbidden_keywords": g.forbidden_keywords,
                    "forbidden_sources": g.forbidden_sources,
                    "expected_route": g.expected_route or (
                        "rag" if g.intent == "web_fallback" else g.intent
                    ),
                    "actual_route": resp.metadata.route,
                }
            )

        if rows:
            from evals.runners.ragas_adapter import run as run_ragas

            metrics = run_ragas(rows, scorer=args.scorer)
        else:
            metrics = []
        for row, m in zip(rows, metrics):
            row["ragas_metrics"] = m
            row["forbidden_check"] = forbidden_keywords_check(
                row["answer"], row["forbidden_keywords"]
            )
            row["source_overlap"] = source_overlap(
                row["actual_sources"], row["golden_sources"]
            )
            row["source_precision"] = source_precision(
                row["actual_sources"],
                row["golden_sources"],
                row.get("acceptable_source_groups"),
            )
            row["source_recall"] = source_recall(
                row["actual_sources"],
                row["golden_sources"],
                row.get("acceptable_source_groups"),
            )
            row["forbidden_source_check"] = forbidden_sources_check(
                row["actual_sources"], row["forbidden_sources"]
            )
            row["route_check"] = {
                "passed": row["actual_route"] == row["expected_route"],
                "expected": row["expected_route"],
                "actual": row["actual_route"],
            }

        timestamp = datetime.datetime.now(datetime.timezone.utc)
        out_path = (
            Path(args.output)
            if args.output
            else Path(
                f"evals/reports/results/{timestamp:%Y%m%dT%H%M%SZ}_{args.profile}.json"
            )
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "profile": args.profile,
            "flags": flags,
            "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "filter": args.filter,
            "mode": mode,
            "scorer": args.scorer,
            "preflight": preflight,
            "provenance": _evaluation_provenance(args, preflight),
            "rows": rows,
            "skipped": skipped,
            "aggregate": aggregate(rows),
        }

        thresholds = {
            "faithfulness": args.min_faithfulness,
            "context_precision": args.min_context_precision,
            "context_recall": args.min_context_recall,
            "answer_relevancy": args.min_answer_relevancy,
            "source_precision": args.min_source_precision,
            "source_recall": args.min_source_recall,
        }
        threshold_failures = _aggregate_threshold_failures(payload["aggregate"], thresholds)
        payload["threshold_failures"] = threshold_failures
        per_question_failures = _per_question_threshold_failures(rows, thresholds)
        payload["per_question_threshold_failures"] = per_question_failures
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print_table(payload)
        print(f"\nWrote: {out_path}")
        if args.strict and (
            skipped
            or payload["aggregate"]["forbidden_violations"]
            or payload["aggregate"]["forbidden_source_violations"]
            or payload["aggregate"]["route_violations"]
            or threshold_failures
            or per_question_failures
        ):
            raise SystemExit(
                "strict evaluation gate failed: "
                f"aggregate={threshold_failures}, per_question={per_question_failures}"
            )
    finally:
        if hasattr(invoker, "close"):
            invoker.close()


if __name__ == "__main__":
    main()
