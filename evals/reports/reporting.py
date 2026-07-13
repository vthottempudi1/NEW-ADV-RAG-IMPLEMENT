from __future__ import annotations

from statistics import mean

RAGAS_METRIC_KEYS = {
    "faithfulness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
}

# Source metrics are deterministic retrieval-quality gates stored at the row level rather than
# inside ``ragas_metrics``. Keeping them explicit prevents reports from presenting only the four
# LLM-judged metrics and makes the complete six-metric contract visible to maintainers.
SOURCE_METRIC_KEYS = {
    "source_precision",
    "source_recall",
}

METRIC_KEYS = RAGAS_METRIC_KEYS | SOURCE_METRIC_KEYS


# Learner note: Encapsulates aggregate so this responsibility can be understood, tested, and changed independently.
def aggregate(rows: list[dict]) -> dict:
    """Aggregate RAG evaluation results across multiple rows."""
    out: dict = {}
    for key in RAGAS_METRIC_KEYS:
        values = [
            row["ragas_metrics"].get(key)
            for row in rows
            if row.get("ragas_metrics") and row["ragas_metrics"].get(key) is not None
        ]
        out[key] = round(mean(values), 3) if values else None

    out["forbidden_violations"] = sum(
        1 for row in rows if not row.get("forbidden_check", {}).get("passed", True)
    )
    for key in SOURCE_METRIC_KEYS:
        values = [row.get(key) for row in rows if row.get(key) is not None]
        out[key] = round(mean(values), 3) if values else None
    out["forbidden_source_violations"] = sum(
        1 for row in rows if not row.get("forbidden_source_check", {}).get("passed", True)
    )
    out["route_violations"] = sum(
        1 for row in rows if not row.get("route_check", {}).get("passed", True)
    )
    out["unsupported_claims"] = sum(
        1
        for row in rows
        for claim in (row.get("ragas_metrics") or {}).get("faithfulness_claims", [])
        if not claim.get("supported", False)
    )
    return out


# Learner note: Encapsulates print table so this responsibility can be understood, tested, and changed independently.
def print_table(payload: dict) -> None:
    """Print a markdown table of per-question and aggregate eval results."""
    print(f"\n## Eval - profile={payload['profile']} mode={payload['mode']}")
    print(f"Skipped: {len(payload['skipped'])}")
    print()
    print("| id | feature | route | faith | ctx_prec | src_prec | src_recall | ctx_recall | ans_rel | checks |")
    print("|----|---------|-------|-------|----------|----------|------------|------------|---------|--------|")

    for row in payload["rows"]:
        metrics = row.get("ragas_metrics") or {}
        forbidden = (
            "OK"
            if row["forbidden_check"]["passed"]
            else f"FAIL: {row['forbidden_check']['hits']}"
        )
        source_check = row.get("forbidden_source_check", {"passed": True, "hits": []})
        route_check = row.get("route_check", {"passed": True})
        checks = []
        if forbidden != "OK":
            checks.append(forbidden)
        if not source_check["passed"]:
            checks.append(f"SOURCE_FAIL: {source_check['hits']}")
        if not route_check["passed"]:
            checks.append(
                f"ROUTE_FAIL: {route_check.get('actual')} != {route_check.get('expected')}"
            )
        print(
            f"| {row['id']} | {row['demonstrates_feature']} | {row.get('actual_route')} | "
            f"{metrics.get('faithfulness', 0):.2f} | "
            f"{metrics.get('context_precision', 0):.2f} | "
            f"{row.get('source_precision', 0):.2f} | "
            f"{(row.get('source_recall') if row.get('source_recall') is not None else 1.0):.2f} | "
            f"{metrics.get('context_recall', 0):.2f} | "
            f"{metrics.get('answer_relevancy', 0):.2f} | {'; '.join(checks) or 'OK'} |"
        )

    if not payload["rows"]:
        print("(no rows evaluated - all goldens skipped)")
        return

    aggregate_row = payload["aggregate"]
    print(
        f"| **AGG** | - | - | **{aggregate_row['faithfulness']}** | "
        f"**{aggregate_row['context_precision']}** | "
        f"**{aggregate_row['source_precision']}** | "
        f"**{aggregate_row['source_recall']}** | "
        f"**{aggregate_row['context_recall']}** | "
        f"**{aggregate_row['answer_relevancy']}** | "
        f"violations={aggregate_row['forbidden_violations']}, "
        f"source_violations={aggregate_row['forbidden_source_violations']}, "
        f"route_violations={aggregate_row['route_violations']}, "
        f"unsupported_claims={aggregate_row['unsupported_claims']} |"
    )
