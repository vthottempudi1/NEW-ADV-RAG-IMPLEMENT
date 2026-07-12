import psycopg2
from fastapi import APIRouter, HTTPException, status
from psycopg2 import Error as PsycopgError
from pydantic import BaseModel

from app.config import settings
from app.middleware.auth import create_access_token, hash_password, verify_password


# Learner Note: Auth request is part of the versioned HTTP API boundary.
class AuthRequest(BaseModel):
    """Represent auth request within the versioned HTTP API boundary.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    username: str
    password: str


router = APIRouter(tags=["auth"])


# Learner note: Encapsulates get db connection so this responsibility can be understood, tested, and changed independently.
def _get_db_connection():
    """Support the versioned HTTP API boundary by performing get db connection.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    try:
        return psycopg2.connect(settings.database_url)
    except psycopg2.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database_connection_failed: {exc}",
        ) from exc


# Learner note: Encapsulates register so this responsibility can be understood, tested, and changed independently.
@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: AuthRequest) -> dict:
    """Handle register asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    username = body.username
    password = body.password
    password_hash = hash_password(password)

    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (username, password_hash, False),
        )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Username already exists")
    except PsycopgError as exc:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"auth_register_failed: {exc}",
        ) from exc
    finally:
        cur.close()
        conn.close()

    token = create_access_token(username)
    return {"token": token}


# Learner note: Encapsulates login so this responsibility can be understood, tested, and changed independently.
@router.post("/auth/login")
async def login(body: AuthRequest) -> dict:
    """Handle login asynchronously within the versioned HTTP API boundary.

    Learner Note:
        The async boundary prevents request handling from blocking unrelated work.
    """
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT password_hash, is_admin FROM users WHERE username = %s",
            (body.username,),
        )
        row = cur.fetchone()
    except PsycopgError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"auth_login_failed: {exc}",
        ) from exc
    finally:
        cur.close()
        conn.close()

    if row is None or not verify_password(body.password, row[0]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(body.username, is_admin=bool(row[1]))
    return {"token": token}
