from app.core.graph import _build_sql_response


# Learner note: Verifies test sql count answer is natural language so future changes cannot silently break this expected behavior.
def test_sql_count_answer_is_natural_language():
    """Verify that sql count answer is natural language.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    result = _build_sql_response(
        "How many P1 incidents were resolved last quarter?",
        "select count(*) as count from incidents",
        [{"count": 50}],
    )

    assert result["final_answer"] == "50 P1 incidents were resolved last quarter."
    assert result["metadata"]["sql_rows"] == [{"count": 50}]
    assert result["metadata"]["sql_query"] == "select count(*) as count from incidents"


# Learner note: Verifies test sql empty result is clear so future changes cannot silently break this expected behavior.
def test_sql_empty_result_is_clear():
    """Verify that sql empty result is clear.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    result = _build_sql_response(
        "How many P1 incidents were resolved last quarter?",
        "select count(*) as count from incidents where 1 = 0",
        [],
    )

    assert result["final_answer"] == "No matching records were found."
    assert result["metadata"]["sql_rows"] == []
