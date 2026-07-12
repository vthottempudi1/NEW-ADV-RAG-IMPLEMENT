import datetime

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings

security = HTTPBearer()


# Learner Note: User is part of the cross-cutting request middleware.
class User(BaseModel):
    """Represent user within the cross-cutting request middleware.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    username: str
    is_admin: bool = False


# Learner note: Computes hash password deterministically to support identity, caching, or deduplication.
def hash_password(password: str) -> str:
    """Perform hash password for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# Learner note: Evaluates verify password as a guardrail before later pipeline stages proceed.
def verify_password(password: str, hashed_password: str) -> bool:
    """Perform verify password for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


# Learner note: Transforms create access token centrally so downstream code receives a predictable shape.
def create_access_token(
    username: str,
    expires_delta_seconds: int | None = None,
    is_admin: bool = False,
) -> str:
    """Perform create access token for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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


# Learner note: Retrieves get current user in one place so callers share consistent access behavior.
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Perform get current user for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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

# Learner note: Encapsulates require admin so this responsibility can be understood, tested, and changed independently.
def require_admin(user: User = Depends(get_current_user)) -> User:
    """Perform require admin for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
