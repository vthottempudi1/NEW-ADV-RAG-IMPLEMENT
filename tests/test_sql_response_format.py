from app.core.graph import _build_sql_response


def test_sql_count_answer_is_natural_language():
    result = _build_sql_response(
        "How many P1 incidents were resolved last quarter?",
        "select count(*) as count from incidents",
        [{"count": 50}],
    )

    assert result["final_answer"] == "50 P1 incidents were resolved last quarter."
    assert result["metadata"]["sql_rows"] == [{"count": 50}]
    assert result["metadata"]["sql_query"] == "select count(*) as count from incidents"


def test_sql_empty_result_is_clear():
    result = _build_sql_response(
        "How many P1 incidents were resolved last quarter?",
        "select count(*) as count from incidents where 1 = 0",
        [],
    )

    assert result["final_answer"] == "No matching records were found."
    assert result["metadata"]["sql_rows"] == []
