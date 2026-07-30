from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class QueryCacheService:
    """Tiered semantic-query cache with a Redis (Upstash) backend and an in-memory fallback.

    Caches are organized into named tiers (``intent``, ``rag_answer``, ``sql_gen``,
    ``sql_result``, ``approved_answer``, ``embedding``), each with its own TTL and
    hit/miss/set counters. Every read/write first tries Redis; if Redis is unavailable
    or a call fails, the service transparently falls back to a thread-safe in-memory
    dict and permanently disables Redis for the remainder of the process lifetime
    (until re-initialized). Keys are derived by hashing normalized input so semantically
    identical requests (e.g. same question, different casing/whitespace) collide onto
    the same cache entry.
    """

    _TIERS = ("intent", "rag_answer", "sql_gen", "sql_result", "approved_answer", "embedding")
    _REDIS_PATTERNS = (
        "intent:*",
        "rag_answer:*",
        "sql_gen:*",
        "sql_result:v1:*",
        "approved_answer:*",
        "embedding:*",
    )

    def __init__(self):
        """Set up the Redis client (if configured), the in-memory fallback store, per-tier stats counters, and the lock guarding shared state."""
        self._redis_client: Any | None = self._build_redis_client()
        self._memory_store: dict[str, tuple[float, str]] = {}
        self._stats: dict[str, dict[str, int]] = {
            tier: defaultdict(int) for tier in self._TIERS
        }
        self._lock = threading.RLock()

    def _build_redis_client(self) -> Any | None:
        """Construct an Upstash Redis client from settings, or return None if Upstash config is missing or the client fails to initialize (in which case the in-memory store is used instead)."""
        if not settings.upstash_redis_url or not settings.upstash_redis_token:
            logger.info("Redis cache disabled; missing Upstash config")
            return None
        try:
            from upstash_redis import Redis

            return Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
        except Exception:
            logger.exception("Failed to initialize Redis cache; using in-memory fallback")
            return None

    def _key(self, namespace: str, raw: str) -> str:
        """Build a cache key by SHA-256 hashing `raw` and prefixing it with `namespace`, so keys are fixed-length and free of characters unsafe for Redis."""
        hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{namespace}:{hashed}"

    def intent_key(self, question: str) -> str:
        """Return the cache key for a question's classified intent, normalized by stripping and lowercasing before hashing."""
        return self._key("intent", question.strip().lower())

    def rag_answer_key(self, question: str, cache_context: dict[str, Any] | None = None) -> str:
        """Return the cache key for a RAG answer to `question`. When `cache_context` is provided, it is folded into the hashed payload (as sorted-key JSON) so answers are scoped per context rather than shared across unrelated contexts."""
        raw: str | dict[str, Any] = question.strip()
        if cache_context is not None:
            raw = {"question": question.strip(), "context": cache_context}
        return self._key(
            "rag_answer",
            json.dumps(raw, sort_keys=True) if isinstance(raw, dict) else raw,
        )

    def sql_gen_key(self, question: str) -> str:
        """Return the cache key for a generated SQL statement corresponding to `question`."""
        return self._key("sql_gen", question.strip())

    def sql_result_key(self, sql: str) -> str:
        """Return the cache key for a SQL execution result. The SQL text is whitespace-collapsed and lowercased before hashing so trivially reformatted equivalent queries share a cache entry."""
        return self._key("sql_result:v1", " ".join(sql.split()).strip().lower())

    def embedding_key(self, text: str) -> str:
        """Return the cache key for the embedding vector of `text`."""
        return self._key("embedding", text)

    def approved_answer_key(
        self,
        route: str,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> str:
        """Return the cache key for a human-approved answer, scoped by routing decision (`route`), the original `question`, and optional `cache_context`."""
        raw: dict[str, Any] = {
            "route": route.strip().lower(),
            "question": question.strip(),
            "context": cache_context or {},
        }
        return self._key("approved_answer", json.dumps(raw, sort_keys=True))

    def _record(self, tier: str, field: str) -> None:
        """Increment the named counter (e.g. "hits", "misses", "sets") for the given tier under the shared lock."""
        with self._lock:
            self._stats[tier][field] += 1

    def _disable_redis(self, reason: str, exc: Exception | None = None) -> None:
        """Drop the Redis client so subsequent operations fall back to the in-memory store, logging `reason` (and `exc` if given). No-op if Redis is already disabled."""
        if self._redis_client is None:
            return
        if exc is not None:
            logger.warning("%s; disabling Redis cache: %s", reason, exc)
        else:
            logger.warning("%s; disabling Redis cache", reason)
        self._redis_client = None

    def _get(self, tier: str, key: str) -> str | None:
        """Read `key` from Redis first, falling back to the in-memory store (honoring TTL expiry) if Redis is unavailable or errors. Records a hit/miss for `tier` and disables Redis on read failure. Returns None on a miss or expired entry."""
        if self._redis_client is not None:
            try:
                value = self._redis_client.get(key)
                if value is not None:
                    self._record(tier, "hits")
                    return str(value)
            except Exception as exc:
                logger.exception("Redis get failed for tier=%s", tier)
                self._disable_redis("Redis read failure", exc)

        with self._lock:
            current = self._memory_store.get(key)
            if current is None:
                self._record(tier, "misses")
                return None
            expires_at, value = current
            if expires_at < time.time():
                del self._memory_store[key]
                self._record(tier, "misses")
                return None

        self._record(tier, "hits")
        return value

    def _set(self, tier: str, key: str, value: str, ttl_seconds: int) -> None:
        """Write `value` under `key` with the given TTL, preferring Redis and falling back to the in-memory store (storing an absolute expiry timestamp) if Redis is unavailable or the write fails. Always records a "sets" event for `tier`."""
        self._record(tier, "sets")

        if self._redis_client is not None:
            try:
                self._redis_client.set(key, value, ex=ttl_seconds)
                return
            except Exception as exc:
                logger.exception("Redis set failed for tier=%s", tier)
                self._disable_redis("Redis write failure", exc)

        with self._lock:
            self._memory_store[key] = (time.time() + ttl_seconds, value)

    def _delete(self, tier: str, key: str) -> dict[str, int | bool]:
        """Delete `key` from both Redis and the in-memory store (best-effort on each). Returns a summary dict with the tier, number of Redis entries deleted, whether an in-memory entry was removed, and the key."""
        redis_deleted = 0
        memory_deleted = False

        if self._redis_client is not None:
            try:
                deleted = self._redis_client.delete(key)
                redis_deleted = int(deleted or 0)
            except Exception as exc:
                logger.exception("Redis delete failed for tier=%s", tier)
                self._disable_redis("Redis delete failure", exc)

        with self._lock:
            if key in self._memory_store:
                del self._memory_store[key]
                memory_deleted = True

        return {
            "tier": tier,
            "redis_deleted": redis_deleted,
            "memory_deleted": memory_deleted,
            "key": key,
        }

    def get_intent(self, question: str) -> str | None:
        """Return the cached classified intent for `question`, or None if not cached."""
        return self._get("intent", self.intent_key(question))

    def set_intent(self, question: str, intent: str) -> None:
        """Cache the classified `intent` for `question` for 24 hours."""
        self._set("intent", self.intent_key(question), intent, 86400)

    def clear_intent(self, question: str) -> dict[str, int | bool]:
        """Remove the cached intent for `question` from both backends."""
        return self._delete("intent", self.intent_key(question))

    def get_rag_answer(
        self,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return the cached RAG answer payload for `question`/`cache_context`, or None if missing or the cached JSON payload fails to decode."""
        value = self._get("rag_answer", self.rag_answer_key(question, cache_context))
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.exception("Invalid rag_answer cache payload")
            return None

    def set_rag_answer(
        self,
        question: str,
        answer_payload: dict[str, Any],
        cache_context: dict[str, Any] | None = None,
    ) -> None:
        """Cache `answer_payload` (JSON-serialized) for `question`/`cache_context` for 1 hour."""
        self._set(
            "rag_answer",
            self.rag_answer_key(question, cache_context),
            json.dumps(answer_payload),
            3600,
        )

    def clear_rag_answer(
        self,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, int | bool]:
        """Remove the cached RAG answer for `question`/`cache_context` from both backends."""
        return self._delete("rag_answer", self.rag_answer_key(question, cache_context))

    def get_sql_generation(self, question: str) -> str | None:
        """Return the cached generated SQL text for `question`, or None if not cached."""
        return self._get("sql_gen", self.sql_gen_key(question))

    def set_sql_generation(self, question: str, sql: str) -> None:
        """Cache the generated `sql` statement for `question` for 24 hours."""
        self._set("sql_gen", self.sql_gen_key(question), sql, 86400)

    def clear_sql_generation(self, question: str) -> dict[str, int | bool]:
        """Remove the cached generated SQL for `question` from both backends."""
        return self._delete("sql_gen", self.sql_gen_key(question))

    def get_sql_result(self, sql: str) -> list[dict[str, Any]] | None:
        """Return the cached row list for executing `sql`, or None if not cached, expired, or the cached payload is not a JSON list."""
        value = self._get("sql_result", self.sql_result_key(sql))
        if value is None:
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            logger.exception("Invalid sql_result cache payload")
            return None

    def set_sql_result(self, sql: str, rows: list[dict[str, Any]]) -> None:
        """Cache the result `rows` of executing `sql` for 15 minutes."""
        self._set(
            "sql_result",
            self.sql_result_key(sql),
            json.dumps(rows),
            900,
        )

    def clear_sql_result(self, sql: str) -> dict[str, int | bool]:
        """Remove the cached result rows for `sql` from both backends."""
        return self._delete("sql_result", self.sql_result_key(sql))

    def get_approved_answer(
        self,
        route: str,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return the cached human-approved answer payload for the given `route`/`question`/`cache_context`, or None if missing or undecodable."""
        value = self._get(
            "approved_answer",
            self.approved_answer_key(route, question, cache_context),
        )
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.exception("Invalid approved_answer cache payload")
            return None

    def set_approved_answer(
        self,
        route: str,
        question: str,
        answer_payload: dict[str, Any],
        cache_context: dict[str, Any] | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        """Cache `answer_payload` as the approved answer for `route`/`question`/`cache_context`, with a default TTL of 15 minutes (overridable via `ttl_seconds`)."""
        self._set(
            "approved_answer",
            self.approved_answer_key(route, question, cache_context),
            json.dumps(answer_payload),
            ttl_seconds,
        )

    def clear_approved_answer(
        self,
        route: str,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, int | bool]:
        """Remove the cached approved answer for `route`/`question`/`cache_context` from both backends."""
        return self._delete(
            "approved_answer",
            self.approved_answer_key(route, question, cache_context),
        )

    def get_embedding(self, text: str) -> list[float] | None:
        """Return the cached embedding vector for `text`, or None if missing or the cached payload is not a JSON list."""
        value = self._get("embedding", self.embedding_key(text))
        if value is None:
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            logger.exception("Invalid embedding cache payload")
            return None

    def set_embedding(self, text: str, vector: list[float]) -> None:
        """Cache the embedding `vector` for `text` for 7 days."""
        self._set(
            "embedding",
            self.embedding_key(text),
            json.dumps(vector),
            604800,
        )

    def clear_embedding(self, text: str) -> dict[str, int | bool]:
        """Remove the cached embedding for `text` from both backends."""
        return self._delete("embedding", self.embedding_key(text))

    def stats(self) -> dict[str, dict[str, float | int]]:
        """Return a snapshot of hits/misses/sets and computed hit rate for every cache tier."""
        snapshot: dict[str, dict[str, float | int]] = {}
        with self._lock:
            for tier in self._TIERS:
                hits = int(self._stats[tier]["hits"])
                misses = int(self._stats[tier]["misses"])
                sets = int(self._stats[tier]["sets"])
                total = hits + misses
                hit_rate = (hits / total) if total else 0.0
                snapshot[tier] = {
                    "hits": hits,
                    "misses": misses,
                    "sets": sets,
                    "hit_rate": hit_rate,
                }
        return snapshot

    def clear(self, reset_stats: bool = True) -> list[str]:
        """Flush every cache tier from both backends: scans and deletes all keys matching the known Redis key patterns, then clears the in-memory store. Optionally resets the hit/miss/set counters (default True). Returns a list of human-readable summary strings, one per backend actually cleared."""
        cleared: list[str] = []

        if self._redis_client is not None:
            try:
                total_deleted = 0
                for pattern in self._REDIS_PATTERNS:
                    cursor = 0
                    while True:
                        cursor, keys = self._redis_client.scan(cursor, match=pattern, count=200)
                        if keys:
                            total_deleted += int(self._redis_client.delete(*keys) or 0)
                        if cursor == 0:
                            break
                cleared.append(f"redis ({total_deleted} entries)")
            except Exception as exc:
                logger.exception("Redis clear-all failed")
                self._disable_redis("Redis clear-all failure", exc)

        with self._lock:
            count = len(self._memory_store)
            self._memory_store.clear()
            if reset_stats:
                for tier in self._TIERS:
                    self._stats[tier] = defaultdict(int)
            cleared.append(f"memory ({count} entries)")

        return cleared


query_cache = QueryCacheService()
