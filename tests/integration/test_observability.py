import logging

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# Learner note: Verifies request correlation and timing logs so production diagnostics remain dependable.
def test_request_middleware_returns_request_id_and_logs_completion(caplog):
    """Verify that request middleware returns request id and logs completion.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    with caplog.at_level(logging.INFO, logger="app.main"):
        response = client.get("/health", headers={"x-request-id": "learner-request-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "learner-request-123"
    assert any(
        "request_complete" in record.message
        and "duration_ms=" in record.message
        and "request_id=learner-request-123" in record.message
        for record in caplog.records
    )
