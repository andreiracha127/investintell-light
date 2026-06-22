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


class _Req(BaseModel):
    ticker: str
    seed: int | None = None


class _Resp(BaseModel):
    value: float


@pytest.mark.asyncio
async def test_decorator_caches_and_rehydrates_model(monkeypatch):
    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": True, "result_cache_ttl_seconds": 60})())

    @rc.cached_result("beta")
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=1.5)

    r1 = await _svc(None, _Req(ticker="AAPL"))
    r2 = await _svc(None, _Req(ticker="AAPL"))
    assert isinstance(r1, _Resp) and r1.value == 1.5
    assert r2.value == 1.5
    assert calls["n"] == 1  # segunda chamada veio do cache


@pytest.mark.asyncio
async def test_decorator_bypasses_when_flag_off(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": False, "result_cache_ttl_seconds": 60})())

    @rc.cached_result("beta")
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=2.0)

    await _svc(None, _Req(ticker="AAPL"))
    await _svc(None, _Req(ticker="AAPL"))
    assert calls["n"] == 2  # sem cache, recomputa sempre


@pytest.mark.asyncio
async def test_decorator_skips_when_not_cacheable(monkeypatch):
    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": True, "result_cache_ttl_seconds": 60})())

    # monte-carlo sem seed → não cacheável
    @rc.cached_result("monte_carlo", cacheable=lambda p: p.seed is not None)
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=3.0)

    await _svc(None, _Req(ticker="AAPL", seed=None))
    await _svc(None, _Req(ticker="AAPL", seed=None))
    assert calls["n"] == 2          # sem seed nunca cacheia
    assert store == {}              # nada gravado
    await _svc(None, _Req(ticker="AAPL", seed=42))
    await _svc(None, _Req(ticker="AAPL", seed=42))
    assert calls["n"] == 3          # com seed: computou 1×, depois hit
