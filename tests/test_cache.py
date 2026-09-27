from astra_pc.core.cache import ResponseCache


def test_response_cache(tmp_path):
    cache = ResponseCache(tmp_path / "cache.db", ttl=60)
    key = cache.key("hello", "default")
    assert cache.get(key) is None
    cache.put(key, "world")
    assert cache.get(key) == "world"
