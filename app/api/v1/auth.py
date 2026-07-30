import psycopg2
from fastapi import APIRouter, HTTPException, status
from psycopg2 import Error as PsycopgError
from pydantic import BaseModel

from app.config import settings
from app.middleware.auth import create_access_token, hash_password, verify_password


class AuthRequest(BaseModel):
    """Request body for register/login: a plaintext username and password pair."""

    username: str
    password: str


router = APIRouter(tags=["auth"])


def _get_db_connection():
    """Open a new psycopg2 connection to the configured database, raising HTTP 503 if the database is unreachable."""
    try:
        return psycopg2.connect(settings.database_url)
    except psycopg2.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database_connection_failed: {exc}",
        ) from exc


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: AuthRequest) -> dict:
    """Create a new non-admin user with a bcrypt-hashed password and return a signed access token.

    Raises HTTP 400 if the username is already taken, or HTTP 500 on other database
    errors. The transaction is rolled back on any failure and the connection is
    always closed.
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


@router.post("/auth/login")
async def login(body: AuthRequest) -> dict:
    """Verify credentials against the stored password hash and return a signed access token.

    Raises HTTP 401 if the username doesn't exist or the password doesn't match,
    and HTTP 500 on database errors. The returned token embeds the user's
    admin flag from the database.
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
