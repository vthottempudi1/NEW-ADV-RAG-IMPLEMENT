import time

from upstash_redis import Redis

from app.config import settings

_redis_client: Redis | None = None


# Learner note: Retrieves get redis client in one place so callers share consistent access behavior.
def get_redis_client() -> Redis:
    """Perform get redis client for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis(
            url=settings.upstash_redis_url,
            token=settings.upstash_redis_token,
        )
    return _redis_client


# Learner Note: Rate limiter is part of the cross-cutting request middleware.
class RateLimiter:
    # Learner note: Initializes this component so its dependencies and runtime state are explicit.
    """Represent rate limiter within the cross-cutting request middleware.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def __init__(self, max_requests: int, window_seconds: int = 60):
        """Initialize init dependencies and runtime state.

        Learner Note:
            Explicit initialization keeps object construction predictable and testable.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    # Learner note: Evaluates is allowed as a guardrail before later pipeline stages proceed.
    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """Perform is allowed for the cross-cutting request middleware.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        try:
            client = get_redis_client()
            now = time.time()
            window_start = now - self.window_seconds

            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, self.window_seconds)
            results = pipe.exec()

            request_count = int(results[2])
            remaining = max(0, self.max_requests - request_count)
            allowed = request_count <= self.max_requests
            return allowed, remaining, request_count
        except Exception:
            # Fail open if Redis is unavailable
            return True, self.max_requests, 0


# Learner note: Evaluates is allowed user as a guardrail before later pipeline stages proceed.
def is_allowed_user(
    user_id: str,
    limit: int = 20,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """Perform is allowed user for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:user:{user_id}"
    return limiter.is_allowed(key)

# Learner note: Retrieves get rate limit key in one place so callers share consistent access behavior.
def get_rate_limit_key(user_id: str) -> str:
    """Perform get rate limit key for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return f"rate_limit:user:{user_id}"


# Learner note: Retrieves get rate limit count in one place so callers share consistent access behavior.
def get_rate_limit_count(user_id: str) -> int:
    """Perform get rate limit count for the cross-cutting request middleware.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    try:
        client = get_redis_client()
        key = get_rate_limit_key(user_id)
        result = client.zcard(key)
        return int(result or 0)
    except Exception:
        return 0
