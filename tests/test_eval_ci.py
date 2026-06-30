from Eval.invokers import FixtureInvoker
from Eval.ragas_adapter import run as run_ragas
from Eval.schema import load_goldens


def test_fixture_invoker_supports_hybrid_and_sql_goldens():
    goldens = load_goldens("Eval/seed_questions.yaml")
    invoker = FixtureInvoker(goldens)

    hybrid = next(g for g in goldens if g.intent == "hybrid")
    sql = next(g for g in goldens if g.intent == "sql")

    hybrid_resp, hybrid_chunks = invoker.invoke(hybrid.question, {}, hybrid.intent)
    sql_resp, sql_chunks = invoker.invoke(sql.question, {}, sql.intent)

    assert hybrid_resp.metadata.route == "hybrid"
    assert hybrid_resp.sources == hybrid.golden_sources
    assert len(hybrid_chunks) == len(hybrid.golden_sources)

    assert sql_resp.metadata.route == "sql"
    assert sql_resp.sources == sql.golden_sources
    assert len(sql_chunks) == len(sql.golden_sources)


def test_heuristic_ragas_scoring_returns_metric_keys():
    rows = [
        {
            "id": "q-001",
            "question": "What is a Pod in Kubernetes?",
            "answer": "A pod is the smallest deployable unit in Kubernetes and can contain one or more containers.",
            "contexts": [
                "A pod is the smallest deployable unit in Kubernetes. It can run one or more containers in a shared namespace."
            ],
            "ground_truth": "pod, container, namespace",
        }
    ]

    scored = run_ragas(rows, scorer="heuristic")

    assert len(scored) == 1
    metrics = scored[0]
    assert "faithfulness" in metrics
    assert "answer_relevancy" in metrics
    assert "context_precision" in metrics
    assert "context_recall" in metrics
    assert all(0.0 <= metrics[key] <= 1.0 for key in (
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    ))
