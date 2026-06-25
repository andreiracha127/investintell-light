"""Tests for the portfolio_drift_status persistence layer (Sprint C, Task 1).

Two layers are covered without a live database:

- Model metadata: the ``portfolio_drift_status`` table is registered with the
  expected columns, types, FK cascade and the worst_status CHECK constraint.
  These are offline inspections of ``Base.metadata`` (same style as
  test_portfolio_constraints.py / test_optimize_jobs.py).
- CRUD service: ``upsert_drift_status`` / ``get_drift_status`` are exercised
  against a small in-memory fake AsyncSession that mimics the slice of
  AsyncSession the service uses (add/get/flush). The contract asserted is the
  one Sprint C's drift worker + endpoint depend on: upsert creates a row; a
  second upsert updates the same row (no duplicate); get returns the typed
  dataclass; get(missing) -> None; the breaches dict (nested lists + an ISO
  date string) round-trips intact.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB

# Importing Base triggers app.models.__init__, registering every ORM model.
from app.models import Base
from app.models.portfolio_drift_status import PortfolioDriftStatus
from app.services import portfolio_drift as svc

# ---------------------------------------------------------------------------
# Fake AsyncSession — dict-backed store for drift rows keyed by portfolio_id.
# Mirrors only the operations the service uses (add/get/flush).
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    """Minimal async session backed by an in-memory model store.

    ``rows`` maps portfolio_id -> PortfolioDriftStatus. The service only ever
    ``get``s a row by its portfolio_id PK and ``add``s a new one, so that is
    all this fake implements.
    """

    def __init__(self) -> None:
        self.rows: dict[int, PortfolioDriftStatus] = {}

    def add(self, obj: Any) -> None:
        if isinstance(obj, PortfolioDriftStatus):
            self.rows[obj.portfolio_id] = obj
        else:  # pragma: no cover - defensive
            raise TypeError(f"unexpected add: {type(obj)!r}")

    async def get(self, model: type, pk: Any) -> PortfolioDriftStatus | None:
        if model is PortfolioDriftStatus:
            return self.rows.get(pk)
        raise NotImplementedError  # pragma: no cover

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.fixture
def session() -> FakeAsyncSession:
    return FakeAsyncSession()


_PID = 42
_NOW = dt.datetime(2026, 6, 20, 12, 0, tzinfo=dt.UTC)
_BREACHES = {
    "position_drifts": [
        {"ticker": "AAPL", "target": 0.2, "actual": 0.27, "status": "urgent"},
        {"ticker": "MSFT", "target": 0.1, "actual": 0.12, "status": "maintenance"},
    ],
    "class_breaches": [
        {"asset_class": "equity", "max_weight": 0.6, "actual": 0.71},
    ],
    "overlap_breaches": [
        {"pair": ["VTI", "VOO"], "overlap": 0.83, "cap": 0.5},
    ],
    "overlap_report_date": "2026-05-31",
}


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------


def test_drift_status_table_registered() -> None:
    assert "portfolio_drift_status" in Base.metadata.tables


def test_drift_status_pk_is_portfolio_id() -> None:
    table = Base.metadata.tables["portfolio_drift_status"]
    pk_cols = list(table.primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "portfolio_id"


def test_drift_status_columns_and_types() -> None:
    table = Base.metadata.tables["portfolio_drift_status"]
    assert isinstance(table.c["evaluated_at"].type, DateTime)
    assert table.c["evaluated_at"].type.timezone is True
    assert table.c["evaluated_at"].nullable is False
    assert isinstance(table.c["worst_status"].type, Text)
    assert table.c["worst_status"].nullable is False
    assert isinstance(table.c["breaches"].type, JSONB)
    assert table.c["breaches"].nullable is False


def test_drift_status_fk_cascade() -> None:
    table = Base.metadata.tables["portfolio_drift_status"]
    fks = list(table.c["portfolio_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "portfolios"
    assert fks[0].ondelete == "CASCADE"


def test_drift_status_worst_status_check() -> None:
    table = Base.metadata.tables["portfolio_drift_status"]
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert "ck_portfolio_drift_status_worst_status" in checks


# ---------------------------------------------------------------------------
# CRUD service
# ---------------------------------------------------------------------------


async def test_upsert_creates_row(session: FakeAsyncSession) -> None:
    await svc.upsert_drift_status(
        session,
        _PID,
        evaluated_at=_NOW,
        worst_status="urgent",
        breaches=_BREACHES,
    )
    assert _PID in session.rows
    row = session.rows[_PID]
    assert row.evaluated_at == _NOW
    assert row.worst_status == "urgent"
    assert row.breaches == _BREACHES


async def test_second_upsert_updates_same_row(session: FakeAsyncSession) -> None:
    await svc.upsert_drift_status(
        session,
        _PID,
        evaluated_at=_NOW,
        worst_status="urgent",
        breaches=_BREACHES,
    )
    later = _NOW + dt.timedelta(days=1)
    new_breaches = {
        "position_drifts": [],
        "class_breaches": [],
        "overlap_breaches": [],
        "overlap_report_date": None,
    }
    await svc.upsert_drift_status(
        session,
        _PID,
        evaluated_at=later,
        worst_status="ok",
        breaches=new_breaches,
    )
    # No duplicate — still one row for the portfolio.
    assert len(session.rows) == 1
    row = session.rows[_PID]
    assert row.evaluated_at == later
    assert row.worst_status == "ok"
    assert row.breaches == new_breaches


async def test_get_returns_typed(session: FakeAsyncSession) -> None:
    await svc.upsert_drift_status(
        session,
        _PID,
        evaluated_at=_NOW,
        worst_status="maintenance",
        breaches=_BREACHES,
    )
    result = await svc.get_drift_status(session, _PID)
    assert result is not None
    assert isinstance(result, svc.DriftStatus)
    assert result.portfolio_id == _PID
    assert result.evaluated_at == _NOW
    assert result.worst_status == "maintenance"
    assert isinstance(result.breaches, dict)


async def test_get_missing_returns_none(session: FakeAsyncSession) -> None:
    assert await svc.get_drift_status(session, 999) is None


async def test_breaches_dict_round_trips(session: FakeAsyncSession) -> None:
    await svc.upsert_drift_status(
        session,
        _PID,
        evaluated_at=_NOW,
        worst_status="urgent",
        breaches=_BREACHES,
    )
    result = await svc.get_drift_status(session, _PID)
    assert result is not None
    # Nested lists and the ISO date string survive intact.
    assert result.breaches == _BREACHES
    assert result.breaches["overlap_report_date"] == "2026-05-31"
    assert result.breaches["position_drifts"][0]["ticker"] == "AAPL"
    assert result.breaches["overlap_breaches"][0]["pair"] == ["VTI", "VOO"]
