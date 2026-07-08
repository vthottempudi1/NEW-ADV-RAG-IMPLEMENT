from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from Eval.reporting import aggregate, print_table
from Eval.invokers import (
    FixtureInvoker,
    HttpServiceInvoker,
    ServiceInvoker,
    SkippedIntent,
)
from Eval.post_checks import forbidden_keywords_check, source_overlap
from Eval.profiles import PROFILES
from Eval.schema import load_goldens


def _local_corpus_preflight(goldens) -> dict | None:
    try:
        from app.config import settings
        from app.services.vector_store import get_client
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


def main() -> None:
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
        default="Eval/seed_questions.yaml",
        help="Path to seed questions YAML",
    )
    ap.add_argument(
        "--filter",
        default=None,
        help="Only run goldens with demonstrates_feature == FILTER (plus baseline)",
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
        help="Output JSON path (default: Eval/results/<timestamp>_<profile>.json)",
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
    args = ap.parse_args()
    flags = PROFILES[args.profile]
    goldens = load_goldens(args.questions)

    if args.filter:
        goldens = [
            g
            for g in goldens
            if g.demonstrates_feature in (args.filter, "baseline")
        ]

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
                    "contexts": [c.text for c in chunks],
                    "ground_truth": ", ".join(g.golden_answer_keywords),
                    "actual_sources": resp.sources,
                    "golden_sources": g.golden_sources,
                    "forbidden_keywords": g.forbidden_keywords,
                }
            )

        if rows:
            from Eval.ragas_adapter import run as run_ragas

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

        timestamp = datetime.datetime.now(datetime.timezone.utc)
        out_path = (
            Path(args.output)
            if args.output
            else Path(
                f"Eval/results/{timestamp:%Y%m%dT%H%M%SZ}_{args.profile}.json"
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
            "rows": rows,
            "skipped": skipped,
            "aggregate": aggregate(rows),
        }

        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print_table(payload)
        print(f"\nWrote: {out_path}")
    finally:
        if hasattr(invoker, "close"):
            invoker.close()


if __name__ == "__main__":
    main()
