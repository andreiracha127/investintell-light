from app.services import jobs as jobs_svc


def test_should_run_async_thresholds(monkeypatch):
    monkeypatch.setattr(jobs_svc, "get_settings", lambda: type("S", (), {
        "use_async_jobs": True,
        "async_job_threshold_n_simulations": 20000,
        "async_job_threshold_n_splits": 12,
    })())
    assert jobs_svc.should_run_async(n_simulations=30000) is True
    assert jobs_svc.should_run_async(n_simulations=10000) is False
    assert jobs_svc.should_run_async(n_splits=24) is True
    assert jobs_svc.should_run_async(n_splits=6) is False


def test_should_run_async_off_when_flag_off(monkeypatch):
    monkeypatch.setattr(jobs_svc, "get_settings", lambda: type("S", (), {
        "use_async_jobs": False,
        "async_job_threshold_n_simulations": 20000,
        "async_job_threshold_n_splits": 12,
    })())
    assert jobs_svc.should_run_async(n_simulations=50000) is False


def test_params_hash_is_deterministic():
    from app.schemas.monte_carlo import MonteCarloRequest

    a = jobs_svc.params_hash("portfolio_mc", MonteCarloRequest(ticker="AAPL", seed=1))
    b = jobs_svc.params_hash("portfolio_mc", MonteCarloRequest(ticker="AAPL", seed=1))
    assert a == b and len(a) == 64
