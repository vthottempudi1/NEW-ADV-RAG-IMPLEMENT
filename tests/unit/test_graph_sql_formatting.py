from app.core.graph import _build_operational_hybrid_answer, _format_sql_answer


# Learner note: Verifies test format sql answer for cluster details no exact match so future changes cannot silently break this expected behavior.
def test_format_sql_answer_for_cluster_details_no_exact_match():
    """Verify that format sql answer for cluster details no exact match.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    answer = _format_sql_answer("Show me details for cluster prod-us-east-1", [])
    assert answer == "No exact cluster matched 'prod-us-east-1'."


# Learner note: Verifies test format sql answer for oncall top engineer so future changes cannot silently break this expected behavior.
def test_format_sql_answer_for_oncall_top_engineer():
    """Verify that format sql answer for oncall top engineer.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    answer = _format_sql_answer(
        "Which on-call engineer has been paged the most times this month?",
        [{"engineer": "carol.osei", "page_count": 95}],
    )
    assert answer == "The on-call engineer paged the most times this month is carol.osei with 95 pages."


# Learner note: Verifies test build operational hybrid answer uses runbook first steps so future changes cannot silently break this expected behavior.
def test_build_operational_hybrid_answer_uses_runbook_first_steps():
    """Verify that build operational hybrid answer uses runbook first steps.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    answer = _build_operational_hybrid_answer(
        question="How many open P2 alerts exist right now and what does our runbook say to do first?",
        rows=[{"open_p2_alerts": 3052}],
        rag_metadata={
            "retrieved_chunks": [
                {
                    "text": (
                        "Incident Response Runbook. The first response steps are: establish severity, "
                        "confirm the affected cluster or service, review recent changes, inspect alerts "
                        "and logs, and begin mitigation to reduce user impact."
                    )
                }
            ]
        },
    )
    assert answer is not None
    assert "3052 open P2 alerts" in answer
    assert "establish severity" in answer
