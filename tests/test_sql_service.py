from app.services import sql_service as sql_service_module
from app.services.sql_service import SQLService, is_select_only


def test_is_select_only_allows_select():
    assert is_select_only("select * from users") is True


def test_is_select_only_allows_cte_select():
    assert is_select_only("with recent as (select * from users) select * from recent") is True


def test_is_select_only_allows_union_select():
    assert is_select_only("select id from users union select id from users") is True


def test_is_select_only_blocks_drop():
    assert is_select_only("drop table users") is False


def test_is_select_only_blocks_multi_statement():
    assert is_select_only("select * from users; drop table users") is False


def test_is_select_only_blocks_explain_command():
    assert is_select_only("explain select * from users") is False


def test_is_select_only_blocks_select_into():
    assert is_select_only("select * into temp new_users from users") is False


def test_prepare_sql_question_strips_hybrid_runbook_tail():
    question = "How many open P2 alerts exist right now and what does our runbook say to do first?"
    assert SQLService._prepare_sql_question(question) == "How many open P2 alerts exist right now"


def test_heuristic_sql_for_oncall_anchors_to_latest_month():
    heuristic = SQLService._heuristic_sql(
        "Which on-call engineer has been paged the most times this month?"
    )
    assert heuristic is not None
    assert "CURRENT_DATE" in heuristic["sql"]
    assert "GROUP BY engineer" in heuristic["sql"]


def test_heuristic_sql_for_cluster_details_normalizes_cluster_name():
    heuristic = SQLService._heuristic_sql("Show me details for cluster prod-us-east-1")
    assert heuristic is not None
    assert "FROM clusters" in heuristic["sql"]
    assert "productionuseast1" in heuristic["sql"]
    assert "lower(environment) = 'production'" in heuristic["sql"]
    assert "lower(region) = 'us-east-1'" in heuristic["sql"]


def test_generate_sql_reports_llm_generation_cost(monkeypatch):
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
