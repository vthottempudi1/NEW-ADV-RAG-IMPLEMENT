from __future__ import annotations

from statistics import mean


METRIC_KEYS = {
    "faithfulness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
}


def aggregate(rows: list[dict]) -> dict:
    """Aggregate RAG evaluation results across multiple rows."""
    out: dict = {}
    for key in METRIC_KEYS:
        values = [
            row["ragas_metrics"].get(key)
            for row in rows
            if row.get("ragas_metrics") and row["ragas_metrics"].get(key) is not None
        ]
        out[key] = round(mean(values), 3) if values else None

    out["forbidden_violations"] = sum(
        1 for row in rows if not row.get("forbidden_check", {}).get("passed", True)
    )
    return out


def print_table(payload: dict) -> None:
    """Print a markdown table of per-question and aggregate eval results."""
    print(f"\n## Eval - profile={payload['profile']} mode={payload['mode']}")
    print(f"Skipped: {len(payload['skipped'])}")
    print()
    print("| id | feature | faith | ctx_prec | ctx_recall | ans_rel | forbidden |")
    print("|----|---------|-------|----------|------------|---------|-----------|")

    for row in payload["rows"]:
        metrics = row.get("ragas_metrics") or {}
        forbidden = (
            "OK"
            if row["forbidden_check"]["passed"]
            else f"FAIL: {row['forbidden_check']['hits']}"
        )
        print(
            f"| {row['id']} | {row['demonstrates_feature']} | "
            f"{metrics.get('faithfulness', 0):.2f} | "
            f"{metrics.get('context_precision', 0):.2f} | "
            f"{metrics.get('context_recall', 0):.2f} | "
            f"{metrics.get('answer_relevancy', 0):.2f} | {forbidden} |"
        )

    if not payload["rows"]:
        print("(no rows evaluated - all goldens skipped)")
        return

    aggregate_row = payload["aggregate"]
    print(
        f"| **AGG** | - | **{aggregate_row['faithfulness']}** | "
        f"**{aggregate_row['context_precision']}** | "
        f"**{aggregate_row['context_recall']}** | "
        f"**{aggregate_row['answer_relevancy']}** | "
        f"violations={aggregate_row['forbidden_violations']} |"
    )
