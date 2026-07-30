import datetime

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings

security = HTTPBearer()


class User(BaseModel):
    """Authenticated user identity extracted from a validated JWT: username plus admin flag."""

    username: str
    is_admin: bool = False


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (random per-call salt) and return it as a UTF-8 string."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Return True if `password` matches the bcrypt hash `hashed_password`."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(
    username: str,
    expires_delta_seconds: int | None = None,
    is_admin: bool = False,
) -> str:
    """Issue a signed JWT (HS256) encoding `username`, `is_admin`, issued-at, and expiry.

    `expires_delta_seconds` defaults to `settings.jwt_expiration_minutes * 60` when
    not given. Signed with `settings.jwt_secret`.
    """
    if expires_delta_seconds is None:
        expires_delta_seconds = settings.jwt_expiration_minutes * 60

    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=expires_delta_seconds
    )

    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "is_admin": is_admin,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """FastAPI dependency that decodes and validates the bearer JWT, returning the authenticated User.

    Raises HTTP 401 if the token is missing a valid `sub` claim, has expired, or
    otherwise fails signature/algorithm validation.
    """
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        is_admin = bool(payload.get("is_admin", False))
        return User(username=username, is_admin=is_admin)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from None

def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency that builds on `get_current_user` and raises HTTP 403 unless the user has admin privileges."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
