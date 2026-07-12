from app.sql import service as sql_service_module
from app.sql.service import SQLService, is_select_only


# Learner note: Verifies test is select only allows select so future changes cannot silently break this expected behavior.
def test_is_select_only_allows_select():
    """Verify that is select only allows select.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("select * from users") is True


# Learner note: Verifies test is select only allows cte select so future changes cannot silently break this expected behavior.
def test_is_select_only_allows_cte_select():
    """Verify that is select only allows cte select.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("with recent as (select * from users) select * from recent") is True


# Learner note: Verifies test is select only allows union select so future changes cannot silently break this expected behavior.
def test_is_select_only_allows_union_select():
    """Verify that is select only allows union select.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("select id from users union select id from users") is True


# Learner note: Verifies test is select only blocks drop so future changes cannot silently break this expected behavior.
def test_is_select_only_blocks_drop():
    """Verify that is select only blocks drop.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("drop table users") is False


# Learner note: Verifies test is select only blocks multi statement so future changes cannot silently break this expected behavior.
def test_is_select_only_blocks_multi_statement():
    """Verify that is select only blocks multi statement.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("select * from users; drop table users") is False


# Learner note: Verifies test is select only blocks explain command so future changes cannot silently break this expected behavior.
def test_is_select_only_blocks_explain_command():
    """Verify that is select only blocks explain command.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("explain select * from users") is False


# Learner note: Verifies test is select only blocks select into so future changes cannot silently break this expected behavior.
def test_is_select_only_blocks_select_into():
    """Verify that is select only blocks select into.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    assert is_select_only("select * into temp new_users from users") is False


# Learner note: Verifies test prepare sql question strips hybrid runbook tail so future changes cannot silently break this expected behavior.
def test_prepare_sql_question_strips_hybrid_runbook_tail():
    """Verify that prepare sql question strips hybrid runbook tail.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    question = "How many open P2 alerts exist right now and what does our runbook say to do first?"
    assert SQLService._prepare_sql_question(question) == "How many open P2 alerts exist right now"


# Learner note: Verifies test heuristic sql for oncall anchors to latest month so future changes cannot silently break this expected behavior.
def test_heuristic_sql_for_oncall_anchors_to_latest_month():
    """Verify that heuristic sql for oncall anchors to latest month.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    heuristic = SQLService._heuristic_sql(
        "Which on-call engineer has been paged the most times this month?"
    )
    assert heuristic is not None
    assert "CURRENT_DATE" in heuristic["sql"]
    assert "GROUP BY engineer" in heuristic["sql"]


# Learner note: Verifies test heuristic sql for cluster details normalizes cluster name so future changes cannot silently break this expected behavior.
def test_heuristic_sql_for_cluster_details_normalizes_cluster_name():
    """Verify that heuristic sql for cluster details normalizes cluster name.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    heuristic = SQLService._heuristic_sql("Show me details for cluster prod-us-east-1")
    assert heuristic is not None
    assert "FROM clusters" in heuristic["sql"]
    assert "productionuseast1" in heuristic["sql"]
    assert "lower(environment) = 'production'" in heuristic["sql"]
    assert "lower(region) = 'us-east-1'" in heuristic["sql"]


# Learner note: Verifies test generate sql reports llm generation cost so future changes cannot silently break this expected behavior.
def test_generate_sql_reports_llm_generation_cost(monkeypatch):
    """Verify that generate sql reports llm generation cost.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    monkeypatch.setattr(sql_service_module.query_cache, "get_sql_generation", lambda question: None)
    monkeypatch.setattr(sql_service_module.query_cache, "set_sql_generation", lambda question, sql: None)
    monkeypatch.setattr(SQLService, "_heuristic_sql", classmethod(lambda cls, question: None))
    monkeypatch.setattr(SQLService, "_build_schema_context", lambda self: "Database schema:\n  users: id (integer)")
    monkeypatch.setattr(
        sql_service_module,
        "generate",
        lambda **kwargs: {
            "text": '{"sql":"SELECT COUNT(*) AS count FROM users;","explanation":"Count users."}',
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
    )

    result = SQLService().generate_sql("How many users are there?")

    assert result["sql"] == "SELECT COUNT(*) AS count FROM users;"
    assert result["generation_cost_usd"] > 0
