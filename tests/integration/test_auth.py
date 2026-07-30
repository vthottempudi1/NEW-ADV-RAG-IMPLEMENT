from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_api
from app.main import app

client = TestClient(app)


# Note: Versioned API aliases preserve legacy behavior during client migration.
def test_versioned_auth_alias_matches_legacy_contract():
    """Verify that both legacy and `/api/v1` authentication routes validate identically.

    Note:
        Parallel routes allow a non-breaking migration to explicit API versioning.
    """
    legacy = client.post("/auth/login", json={"username": "missing@example.com"})
    versioned = client.post("/api/v1/auth/login", json={"username": "missing@example.com"})

    assert legacy.status_code == 422
    assert versioned.status_code == legacy.status_code


# Note: Swagger should document only canonical versioned routes while aliases stay callable.
def test_openapi_hides_legacy_route_aliases():
    """Prevent duplicate Admin, Auth, Documents, and Query operations in generated API docs."""
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/login" in paths
    assert "/api/v1/query" in paths
    assert "/api/v1/admin/health" in paths
    assert "/auth/login" not in paths
    assert "/query" not in paths
    assert "/admin/health" not in paths


# Note: Verifies test login requires valid json shape so future changes cannot silently break this expected behavior.
def test_login_requires_valid_json_shape():
    """Verify that login requires valid json shape.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    # Note: Fake cursor is part of the automated regression suite.
    class FakeCursor:
        # Note: Supports execute as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake cursor within the automated regression suite.

        Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        # Note: Execute is part of the automated regression suite.
        def execute(self, *args, **kwargs):
            """Perform execute for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

        # Note: Supports fetchone as reusable test setup so scenarios stay deterministic and readable.
        def fetchone(self):
            """Perform fetchone for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

        # Note: Supports close as reusable test setup so scenarios stay deterministic and readable.
        def close(self):
            """Perform close for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

    # Note: Fake connection is part of the automated regression suite.
    class FakeConnection:
        # Note: Supports cursor as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake connection within the automated regression suite.

        Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        # Note: Cursor is part of the automated regression suite.
        def cursor(self):
            """Perform cursor for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return FakeCursor()

        # Note: Supports close as reusable test setup so scenarios stay deterministic and readable.
        def close(self):
            """Perform close for the automated regression suite.

            Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

    auth_api._get_db_connection = lambda: FakeConnection()

    response = client.post(
        "/auth/login",
        json={"username": "missing@example.com", "password": "badpass"},
    )
    assert response.status_code == 401
