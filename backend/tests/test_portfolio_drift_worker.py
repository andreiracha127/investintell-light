"""Tests for the portfolio_drift_daily worker (Sprint C, Task 3).

Two layers, no live database:

- ``materialize_all_portfolio_drifts`` (service) — iterates the target
  portfolios, loads each portfolio + its rebalance policy + its previous drift
  status, calls ``evaluate_portfolio_drift`` (stubbed) and ``upsert_drift_status``
  so each portfolio ends with exactly one drift row carrying the evaluated
  worst_status. Re-running updates the same row (idempotent, no duplicates).
- ``run`` (worker) — mirrors ``portfolio_nav_daily``: acquires an advisory lock
  (skips with ``{"status": "skipped"}`` when not acquired), delegates to
  ``materialize_all_portfolio_drifts``, commits, returns the per-portfolio
  summary and releases the lock.

The service's evaluation + persistence internals are exercised by
test_portfolio_drift_eval.py / test_portfolio_drift_status.py; here we stub the
expensive ``evaluate_portfolio_drift`` and assert the worker orchestration.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.models.portfolio_drift_status import PortfolioDriftStatus
from app.services import portfolio_drift as svc

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePortfolio:
    def __init__(self, pid: int) -> None:
        self.id = pid
        self.positions: list[Any] = []


class FakeAsyncSession:
    """Dict-backed session covering only what the service/worker touch:

    - ``get(PortfolioDriftStatus, pid)`` for upsert/get_drift_status
    - ``add`` of a new drift row
    - ``flush`` / ``commit`` / ``rollback`` / ``scalar`` / ``execute`` no-ops
    - ``__aenter__``/``__aexit__`` so it can stand in for AsyncSessionLocal()
    """

    def __init__(self, *, lock_acquired: bool = True) -> None:
        self.rows: dict[int, PortfolioDriftStatus] = {}
        self.lock_acquired = lock_acquired
        self.committed = 0
        self.lock_calls: list[str] = []

    # --- session protocol ---
    def add(self, obj: Any) -> None:
        if isinstance(obj, PortfolioDriftStatus):
            self.rows[obj.portfolio_id] = obj
        else:  # pragma: no cover - defensive
            raise TypeError(f"unexpected add: {type(obj)!r}")

    async def get(self, model: type, pk: Any) -> Any:
        if model is PortfolioDriftStatus:
            return self.rows.get(pk)
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        return None

    async def scalar(self, *_args: Any, **_kwargs: Any) -> bool:
        self.lock_calls.append("acquire")
        return self.lock_acquired

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        self.lock_calls.append("release")
        return None

    # --- async-context-manager protocol ---
    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Service: materialize_all_portfolio_drifts
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_eval(monkeypatch: pytest.MonkeyPatch) -> dict[int, str]:
    """Stub the dependencies materialize_all_portfolio_drifts pulls in.

    - ``_all_portfolio_ids`` -> the seeded ids
    - ``portfolio_crud.get_portfolio`` -> a FakePortfolio per id
    - ``evaluator.get_policy`` -> None (defaults path)
    - ``evaluate_portfolio_drift`` -> a deterministic status keyed by id
    """
    status_by_id = {1: "ok", 2: "urgent", 3: "maintenance"}

    async def _all_ids(_session: Any) -> list[int]:
        return list(status_by_id)

    async def _get_portfolio(_session: Any, pid: int) -> FakePortfolio:
        return FakePortfolio(pid)

    async def _get_policy(_session: Any, _pid: int) -> None:
        return None

    async def _evaluate(
        _session: Any,
        _datalake: Any,
        portfolio: FakePortfolio,
        *,
        policy: Any,
        previous: Any,
        as_of: dt.date,
    ) -> tuple[str, dict]:
        return status_by_id[portfolio.id], {"position_drifts": [], "as_of": as_of.isoformat()}

    monkeypatch.setattr(svc, "_all_portfolio_ids", _all_ids)
    monkeypatch.setattr(svc.portfolio_crud, "get_portfolio", _get_portfolio)
    monkeypatch.setattr(svc.evaluator, "get_policy", _get_policy)
    monkeypatch.setattr(svc, "evaluate_portfolio_drift", _evaluate)
    return status_by_id


async def test_materialize_subset_writes_evaluated_status(
    patched_eval: dict[int, str],
) -> None:
    session = FakeAsyncSession()
    result = await svc.materialize_all_portfolio_drifts(
        session, None, portfolio_ids=[2], as_of=dt.date(2026, 6, 20)
    )
    # Exactly the requested portfolio gets a row with its evaluated status.
    assert set(session.rows) == {2}
    assert session.rows[2].worst_status == "urgent"
    assert result == {"portfolios": [{"id": 2, "worst_status": "urgent"}]}


async def test_materialize_all_enumerates_every_portfolio(
    patched_eval: dict[int, str],
) -> None:
    session = FakeAsyncSession()
    result = await svc.materialize_all_portfolio_drifts(session, None)
    assert set(session.rows) == {1, 2, 3}
    ids = {p["id"]: p["worst_status"] for p in result["portfolios"]}
    assert ids == {1: "ok", 2: "urgent", 3: "maintenance"}


async def test_materialize_is_idempotent(patched_eval: dict[int, str]) -> None:
    session = FakeAsyncSession()
    await svc.materialize_all_portfolio_drifts(
        session, None, portfolio_ids=[2], as_of=dt.date(2026, 6, 20)
    )
    await svc.materialize_all_portfolio_drifts(
        session, None, portfolio_ids=[2], as_of=dt.date(2026, 6, 21)
    )
    # Re-run updates the same row, not a duplicate.
    assert len(session.rows) == 1
    assert session.rows[2].worst_status == "urgent"


# ---------------------------------------------------------------------------
# Worker: run
# ---------------------------------------------------------------------------


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch):
    from app.jobs.workers import portfolio_drift_daily as wk

    return wk


def _patch_session(monkeypatch: pytest.MonkeyPatch, wk, session: FakeAsyncSession) -> None:
    monkeypatch.setattr(wk, "AsyncSessionLocal", lambda: session)
    # No DATALAKE_DB_URL in tests -> optional datalake session is None.
    monkeypatch.setattr(wk, "_open_datalake", _none_cm)


class _NoneCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def _none_cm() -> _NoneCtx:
    return _NoneCtx()


async def test_run_materializes_for_requested_portfolio(
    monkeypatch: pytest.MonkeyPatch, worker
) -> None:
    session = FakeAsyncSession(lock_acquired=True)
    _patch_session(monkeypatch, worker, session)

    captured: dict[str, Any] = {}

    async def _materialize(
        _session: Any, _datalake: Any, *, portfolio_ids: Any = None, as_of: Any = None
    ) -> dict:
        captured["portfolio_ids"] = portfolio_ids
        captured["as_of"] = as_of
        return {"portfolios": [{"id": 7, "worst_status": "urgent"}]}

    monkeypatch.setattr(
        worker.portfolio_drift, "materialize_all_portfolio_drifts", _materialize
    )

    result = await worker.run(portfolio_ids=[7], as_of=dt.date(2026, 6, 20))

    assert result["status"] == "ok"
    assert result["lock_id"] == worker.ADVISORY_LOCK_ID
    assert result["portfolios"] == [{"id": 7, "worst_status": "urgent"}]
    assert captured["portfolio_ids"] == [7]
    assert captured["as_of"] == dt.date(2026, 6, 20)
    # Lock acquired then released.
    assert "acquire" in session.lock_calls
    assert "release" in session.lock_calls


async def test_run_skips_when_lock_not_acquired(
    monkeypatch: pytest.MonkeyPatch, worker
) -> None:
    session = FakeAsyncSession(lock_acquired=False)
    _patch_session(monkeypatch, worker, session)

    called = False

    async def _materialize(*_a: Any, **_k: Any) -> dict:
        nonlocal called
        called = True
        return {"portfolios": []}

    monkeypatch.setattr(
        worker.portfolio_drift, "materialize_all_portfolio_drifts", _materialize
    )

    result = await worker.run()
    assert result["status"] == "skipped"
    assert result["lock_id"] == worker.ADVISORY_LOCK_ID
    assert called is False
    # No work, and no release of a lock we never held.
    assert "release" not in session.lock_calls
