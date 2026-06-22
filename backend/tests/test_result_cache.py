import pytest
from pydantic import BaseModel

from app.core import result_cache as rc


class _Payload(BaseModel):
    ticker: str
    n: int


def test_key_is_deterministic_and_includes_kind_and_version():
    p = _Payload(ticker="AAPL", n=3)
    k1 = rc.result_cache_key("beta", p)
    k2 = rc.result_cache_key("beta", _Payload(n=3, ticker="AAPL"))  # field order irrelevant
    assert k1 == k2
    assert k1.startswith(f"result:{rc._RESULT_CACHE_VERSION}:beta:")
    # kind participa da chave (isolamento entre tipos de cálculo)
    assert rc.result_cache_key("scenario", p) != k1


def test_portfolio_version_hash_changes_with_positions(monkeypatch):
    class _Pos:
        def __init__(self, t, q, a):
            self.ticker, self.quantity, self.acq_price = t, q, a

    class _Pf:
        def __init__(self, pid, cash, updated, positions):
            self.id, self.cash, self.updated_at, self.positions = pid, cash, updated, positions

    import datetime as dt

    base = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 10, 100.0)])
    same = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 10, 100.0)])
    changed = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 11, 100.0)])
    assert rc.portfolio_version_hash(base) == rc.portfolio_version_hash(same)
    assert rc.portfolio_version_hash(base) != rc.portfolio_version_hash(changed)


@pytest.mark.asyncio
async def test_get_miss_then_set_then_hit(monkeypatch):
    store: dict[str, bytes] = {}

    class _FakeRedis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

        async def ping(self):
            return True

    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: _FakeRedis())
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)
    assert await cache.get("result:x:beta:abc") == b"BODY"


@pytest.mark.asyncio
async def test_fail_open_when_redis_raises(monkeypatch):
    class _BrokenRedis:
        async def get(self, key):
            raise RuntimeError("redis down")

        async def set(self, key, value, ex=None):
            raise RuntimeError("redis down")

    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: _BrokenRedis())
    # get -> trata erro como miss; set -> engole o erro. Nenhum levanta.
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)  # não levanta


@pytest.mark.asyncio
async def test_get_returns_none_when_redis_not_configured(monkeypatch):
    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: None)  # REDIS_URL ausente
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)  # no-op, não levanta
