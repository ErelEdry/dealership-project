"""
Search-cache helpers shared by the API and the offline data jobs.

POST /api/search caches each response in Redis for CACHE_TTL seconds under
SEARCH_CACHE_PREFIX + sha1(request). Anything that rewrites vehicle data (the
pipeline, the scripts/ migrations) calls clear_search_cache() afterwards, so
searches stop serving pre-change results straight away instead of for up to
CACHE_TTL.
"""

from __future__ import annotations

import redis
import structlog

from app.core.config import settings

log = structlog.get_logger()

SEARCH_CACHE_PREFIX = "search:"
CACHE_TTL = 300  # seconds


def clear_search_cache(client: redis.Redis | None = None) -> int:
    """Delete every cached search response. Returns how many keys went.

    Best-effort like the cache itself: a Redis outage is logged, never raised —
    the data change already happened, and stale entries still expire on TTL.
    """
    try:
        client = client or redis.Redis.from_url(settings.redis_url)
        keys = list(client.scan_iter(match=SEARCH_CACHE_PREFIX + "*", count=500))
        if keys:
            client.delete(*keys)
        print(f"  -> search cache cleared ({len(keys)} entries)")
        return len(keys)
    except Exception as e:  # noqa: BLE001 — cache must never break a data job
        log.warning("search_cache_clear_failed", error=str(e))
        print(f"  !! could not clear the search cache ({e}); entries expire within {CACHE_TTL}s")
        return 0
