import psycopg2
from psycopg2 import Error as PsycopgError
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.middleware.auth import create_access_token, hash_password, verify_password


class AuthRequest(BaseModel):
    username: str
    password: str


router = APIRouter(tags=["auth"])


def _get_db_connection():
    try:
        return psycopg2.connect(settings.database_url)
    except psycopg2.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database_connection_failed: {exc}",
        ) from exc


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: AuthRequest) -> dict:
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
