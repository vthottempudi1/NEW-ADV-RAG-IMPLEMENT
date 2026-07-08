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
        self._redis_client: Any | None = self._build_redis_client()
        self._memory_store: dict[str, tuple[float, str]] = {}
        self._stats: dict[str, dict[str, int]] = {
            tier: defaultdict(int) for tier in self._TIERS
        }
        self._lock = threading.RLock()

    def _build_redis_client(self) -> Any | None:
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
        hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{namespace}:{hashed}"

    def intent_key(self, question: str) -> str:
        return self._key("intent", question.strip().lower())

    def rag_answer_key(self, question: str, cache_context: dict[str, Any] | None = None) -> str:
        raw: str | dict[str, Any] = question.strip()
        if cache_context is not None:
            raw = {"question": question.strip(), "context": cache_context}
        return self._key(
            "rag_answer",
            json.dumps(raw, sort_keys=True) if isinstance(raw, dict) else raw,
        )

    def sql_gen_key(self, question: str) -> str:
        return self._key("sql_gen", question.strip())

    def sql_result_key(self, sql: str) -> str:
        return self._key("sql_result:v1", " ".join(sql.split()).strip().lower())

    def embedding_key(self, text: str) -> str:
        return self._key("embedding", text)

    def approved_answer_key(
        self,
        route: str,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> str:
        raw: dict[str, Any] = {
            "route": route.strip().lower(),
            "question": question.strip(),
            "context": cache_context or {},
        }
        return self._key("approved_answer", json.dumps(raw, sort_keys=True))

    def _record(self, tier: str, field: str) -> None:
        with self._lock:
            self._stats[tier][field] += 1

    def _disable_redis(self, reason: str, exc: Exception | None = None) -> None:
        if self._redis_client is None:
            return
        if exc is not None:
            logger.warning("%s; disabling Redis cache: %s", reason, exc)
        else:
            logger.warning("%s; disabling Redis cache", reason)
        self._redis_client = None

    def _get(self, tier: str, key: str) -> str | None:
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
        return self._get("intent", self.intent_key(question))

    def set_intent(self, question: str, intent: str) -> None:
        self._set("intent", self.intent_key(question), intent, 86400)

    def clear_intent(self, question: str) -> dict[str, int | bool]:
        return self._delete("intent", self.intent_key(question))

    def get_rag_answer(
        self,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
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
        return self._delete("rag_answer", self.rag_answer_key(question, cache_context))

    def get_sql_generation(self, question: str) -> str | None:
        return self._get("sql_gen", self.sql_gen_key(question))

    def set_sql_generation(self, question: str, sql: str) -> None:
        self._set("sql_gen", self.sql_gen_key(question), sql, 86400)

    def clear_sql_generation(self, question: str) -> dict[str, int | bool]:
        return self._delete("sql_gen", self.sql_gen_key(question))

    def get_sql_result(self, sql: str) -> list[dict[str, Any]] | None:
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
        self._set(
            "sql_result",
            self.sql_result_key(sql),
            json.dumps(rows),
            900,
        )

    def clear_sql_result(self, sql: str) -> dict[str, int | bool]:
        return self._delete("sql_result", self.sql_result_key(sql))

    def get_approved_answer(
        self,
        route: str,
        question: str,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
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
        return self._delete(
            "approved_answer",
            self.approved_answer_key(route, question, cache_context),
        )

    def get_embedding(self, text: str) -> list[float] | None:
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
        self._set(
            "embedding",
            self.embedding_key(text),
            json.dumps(vector),
            604800,
        )

    def clear_embedding(self, text: str) -> dict[str, int | bool]:
        return self._delete("embedding", self.embedding_key(text))

    def stats(self) -> dict[str, dict[str, float | int]]:
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
