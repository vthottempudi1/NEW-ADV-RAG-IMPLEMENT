from app.services.sql_service import is_select_only


def test_is_select_only_allows_select():
    assert is_select_only("select * from users") is True


def test_is_select_only_blocks_drop():
    assert is_select_only("drop table users") is False