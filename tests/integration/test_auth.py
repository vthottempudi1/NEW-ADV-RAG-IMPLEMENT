from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_api
from app.main import app

client = TestClient(app)


# Learner Note: Versioned API aliases preserve legacy behavior during client migration.
def test_versioned_auth_alias_matches_legacy_contract():
    """Verify that both legacy and `/api/v1` authentication routes validate identically.

    Learner Note:
        Parallel routes allow a non-breaking migration to explicit API versioning.
    """
    legacy = client.post("/auth/login", json={"username": "missing@example.com"})
    versioned = client.post("/api/v1/auth/login", json={"username": "missing@example.com"})

    assert legacy.status_code == 422
    assert versioned.status_code == legacy.status_code


# Learner note: Verifies test login requires valid json shape so future changes cannot silently break this expected behavior.
def test_login_requires_valid_json_shape():
    """Verify that login requires valid json shape.

    Learner Note:
        This regression test protects an expected production behavior from silent changes.
    """
    class FakeCursor:
        # Learner note: Supports execute as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake cursor within the automated regression suite.

        Learner Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        def execute(self, *args, **kwargs):
            """Perform execute for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

        # Learner note: Supports fetchone as reusable test setup so scenarios stay deterministic and readable.
        def fetchone(self):
            """Perform fetchone for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

        # Learner note: Supports close as reusable test setup so scenarios stay deterministic and readable.
        def close(self):
            """Perform close for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

    # Learner Note: Fake connection is part of the automated regression suite.
    class FakeConnection:
        # Learner note: Supports cursor as reusable test setup so scenarios stay deterministic and readable.
        """Represent fake connection within the automated regression suite.

        Learner Note:
            This class groups state and behavior behind a clear, testable contract.
        """
        def cursor(self):
            """Perform cursor for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return FakeCursor()

        # Learner note: Supports close as reusable test setup so scenarios stay deterministic and readable.
        def close(self):
            """Perform close for the automated regression suite.

            Learner Note:
                This function keeps the responsibility explicit for callers, tests, and operators.
            """
            return None

    auth_api._get_db_connection = lambda: FakeConnection()

    response = client.post(
        "/auth/login",
        json={"username": "missing@example.com", "password": "badpass"},
    )
    assert response.status_code == 401
