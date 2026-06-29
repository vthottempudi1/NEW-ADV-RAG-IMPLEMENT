import sys
from pathlib import Path

import pytest

from app.services import query_cache_service

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def disable_redis_cache(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_URL", "")
    monkeypatch.setenv("UPSTASH_REDIS_TOKEN", "")
    monkeypatch.setattr(
        query_cache_service.QueryCacheService,
        "_build_redis_client",
        lambda self: None,
    )
    query_cache_service.query_cache._redis_client = None
    query_cache_service.query_cache.clear()
