"""clear_search_cache: drops only search entries, never raises."""

from app.core.cache import SEARCH_CACHE_PREFIX, clear_search_cache


class FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)

    def scan_iter(self, match, count=None):
        prefix = match.rstrip("*")
        return [k for k in list(self.keys) if k.startswith(prefix)]

    def delete(self, *keys):
        self.keys -= set(keys)


class DownRedis:
    def scan_iter(self, match, count=None):
        raise ConnectionError("redis is down")


def test_clears_only_search_entries():
    r = FakeRedis([SEARCH_CACHE_PREFIX + "a", SEARCH_CACHE_PREFIX + "b", "other:key"])
    assert clear_search_cache(r) == 2
    assert r.keys == {"other:key"}


def test_empty_cache_is_fine():
    assert clear_search_cache(FakeRedis([])) == 0


def test_redis_outage_is_not_raised(capsys):
    assert clear_search_cache(DownRedis()) == 0
    assert "could not clear the search cache" in capsys.readouterr().out
