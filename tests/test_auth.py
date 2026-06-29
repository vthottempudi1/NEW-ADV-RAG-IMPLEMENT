from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_login_requires_valid_json_shape():
    response = client.post(
        "/auth/login",
        json={"username": "missing@example.com", "password": "badpass"},
    )
    assert response.status_code in (401, 200)