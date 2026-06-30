from app.services.sql_service import is_select_only


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
