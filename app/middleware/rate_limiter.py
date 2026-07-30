import time

from upstash_redis import Redis

from app.config import settings

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    """Return the process-wide Upstash Redis client, creating and caching it on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis(
            url=settings.upstash_redis_url,
            token=settings.upstash_redis_token,
        )
    return _redis_client


class RateLimiter:
    """Sliding-window rate limiter backed by a Redis sorted set.

    Each call to `is_allowed` records the current timestamp, evicts entries older
    than the window, and counts remaining entries to decide whether the caller
    is still within `max_requests` per `window_seconds`.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60):
        """Configure the request budget (`max_requests`) allowed per sliding `window_seconds`."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """Record a request for `key` and check it against the sliding-window limit.

        Uses a single Redis pipeline to: drop entries outside the window, add the
        current timestamp, count entries in the window, and refresh the key's TTL.
        Returns `(allowed, remaining, request_count)` where `remaining` is the
        requests still available and `request_count` is the count including this
        one. Fails open (returns `(True, max_requests, 0)`) if Redis is unavailable.
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


def is_allowed_user(
    user_id: str,
    limit: int = 20,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """Check and record a request for `user_id` against a per-user sliding-window limit.

    Convenience wrapper that builds a one-off RateLimiter and the user's Redis key.
    Returns the same `(allowed, remaining, request_count)` tuple as `RateLimiter.is_allowed`.
    """
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:user:{user_id}"
    return limiter.is_allowed(key)

def get_rate_limit_key(user_id: str) -> str:
    """Return the Redis key used to track rate-limit state for `user_id`."""
    return f"rate_limit:user:{user_id}"


def get_rate_limit_count(user_id: str) -> int:
    """Return the current number of requests recorded for `user_id` in the rate-limit window, or 0 if Redis is unavailable."""
    try:
        client = get_redis_client()
        key = get_rate_limit_key(user_id)
        result = client.zcard(key)
        return int(result or 0)
    except Exception:
        return 0
