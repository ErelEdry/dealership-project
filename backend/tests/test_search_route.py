"""POST /api/search handler behaviour (embedder, Qdrant and Redis stubbed)."""

import asyncio
import time
from types import SimpleNamespace

from app.schemas.search import SearchRequest

SLOW = 0.3   # seconds each fake sync call blocks its thread


class _NoCache:
    async def get(self, key):
        return None

    async def set(self, key, value, ex=None):
        pass


class _SlowQdrant:
    def query_points(self, **kw):
        time.sleep(SLOW)
        return SimpleNamespace(points=[])


def _slow_embed(query):
    time.sleep(SLOW)
    return [0.0] * 3


def test_search_does_not_block_the_event_loop(search_route, monkeypatch):
    monkeypatch.setattr(search_route, "embed_query", _slow_embed)
    monkeypatch.setattr(search_route, "get_qdrant", lambda: _SlowQdrant())
    monkeypatch.setattr(search_route, "_redis", _NoCache())

    async def main():
        ticks = 0

        async def ticker():        # stands in for every other request, e.g. /health
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        resp = await search_route.search(SearchRequest(query="family suv"), db=None)
        task.cancel()
        return resp, ticks

    resp, ticks = asyncio.run(main())
    assert resp.count == 0
    # ~60 ticks fit in the 0.6 s of blocking work; a blocked loop gets ~0.
    assert ticks >= 20, f"event loop starved during search ({ticks} ticks)"
