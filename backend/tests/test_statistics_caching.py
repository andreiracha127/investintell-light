import datetime as dt

import pytest

from app.core import result_cache as rc


def _make_min_beta_request():
    from app.schemas.statistics import BetaRequest, TickerRef

    return BetaRequest(
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 6, 1),
        asset_x=TickerRef(kind="ticker", ticker="SPY"),
        asset_y=TickerRef(kind="ticker", ticker="AAPL"),
    )


def _make_min_beta_response():
    from app.schemas.statistics import AxisLabels, BetaResponse, RegressionOut

    return BetaResponse(
        labels=AxisLabels(x="SPY", y="AAPL"),
        scatter=[(0.01, 0.02)],
        regression=RegressionOut(beta=1.0, alpha=0.0, r=0.5, n_points=1),
        regression_line=[(0.0, 0.0), (1.0, 1.0)],
    )


@pytest.mark.asyncio
async def test_beta_service_is_cached(monkeypatch):
    from app.services import statistics as svc

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

    from app.schemas.statistics import BetaResponse

    async def _inner(session, payload, *, max_points) -> BetaResponse:
        calls["n"] += 1
        return _make_min_beta_response()

    # substituir o corpo não-decorado pelo stub e re-decorar
    monkeypatch.setattr(svc, "run_beta", rc.cached_result("stat_beta")(_inner))
    req = _make_min_beta_request()
    r1 = await svc.run_beta(None, req, max_points=100)
    r2 = await svc.run_beta(None, req, max_points=100)
    assert r1.regression.beta == 1.0
    assert r2.regression.beta == 1.0
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_scenario_version_changes_cache_key():
    # _VersionedScenario embeds the portfolio version, so two different versions
    # yield different cache keys (editing the portfolio invalidates the cache).
    from app.services.statistics import _VersionedScenario
    from app.schemas.statistics import ScenarioRequest

    req = ScenarioRequest(
        start_date=dt.date(2026, 1, 1), end_date=dt.date(2026, 6, 1), portfolio_id=1
    )
    v1 = _VersionedScenario(request=req, portfolio_version="aaaa")
    v2 = _VersionedScenario(request=req, portfolio_version="bbbb")
    assert rc.result_cache_key("stat_scenario", v1) != rc.result_cache_key(
        "stat_scenario", v2
    )
