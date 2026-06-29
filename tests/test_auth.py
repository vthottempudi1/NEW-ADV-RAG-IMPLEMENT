from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app


client = TestClient(app)


def test_login_requires_valid_json_shape():
    class FakeCursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return None

        def close(self):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    auth_api._get_db_connection = lambda: FakeConnection()

    response = client.post(
        "/auth/login",
        json={"username": "missing@example.com", "password": "badpass"},
    )
    assert response.status_code == 401
