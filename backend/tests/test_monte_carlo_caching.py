import pytest

from app.core import result_cache as rc
from app.schemas.monte_carlo import MonteCarloRequest


def _make_min_mc_response():
    from app.schemas.monte_carlo import MonteCarloParams, MonteCarloResponse

    return MonteCarloResponse(
        params=MonteCarloParams(
            ticker="AAPL",
            statistic="max_drawdown",
            range="MAX",
            n_simulations=10000,
            risk_free_rate=0.04,
            seed=42,
        ),
        percentiles={"p50": 0.1},
        mean=0.1,
        median=0.1,
        std=0.02,
        historical_value=0.1,
        historical_horizon_days=252,
        historical_percentile_rank=0.5,
        confidence_bars=[],
        degraded=False,
        degraded_reason=None,
    )


def test_request_seed_drives_cacheability():
    seeded = MonteCarloRequest(ticker="AAPL", seed=42)
    unseeded = MonteCarloRequest(ticker="AAPL", seed=None)
    assert (seeded.seed is not None) is True
    assert (unseeded.seed is not None) is False
    # chave determinística para o mesmo seed
    assert rc.result_cache_key("monte_carlo", seeded) == rc.result_cache_key(
        "monte_carlo", MonteCarloRequest(ticker="AAPL", seed=42)
    )
    # seed diferente → chave diferente
    assert rc.result_cache_key("monte_carlo", seeded) != rc.result_cache_key(
        "monte_carlo", MonteCarloRequest(ticker="AAPL", seed=7)
    )


@pytest.mark.asyncio
async def test_projection_caches_only_with_seed(monkeypatch):
    import app.api.routes.monte_carlo as mc_route

    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(
        mc_route,
        "get_settings",
        lambda: type("S", (), {"use_result_cache": True, "result_cache_ttl_seconds": 60})(),
    )

    async def _fake_run(session, **kwargs):
        calls["n"] += 1
        return _make_min_mc_response()

    monkeypatch.setattr(mc_route, "run_monte_carlo", _fake_run)

    # No seed: never cached -> runs twice, store empty.
    await mc_route.project_monte_carlo(MonteCarloRequest(ticker="AAPL", seed=None), None)
    await mc_route.project_monte_carlo(MonteCarloRequest(ticker="AAPL", seed=None), None)
    assert calls["n"] == 2
    assert store == {}

    # With seed: computes once, then hits.
    await mc_route.project_monte_carlo(MonteCarloRequest(ticker="AAPL", seed=42), None)
    await mc_route.project_monte_carlo(MonteCarloRequest(ticker="AAPL", seed=42), None)
    assert calls["n"] == 3
