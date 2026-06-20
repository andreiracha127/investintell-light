"""Tests for the portfolio_constraints persistence layer (Sprint B, Task 2).

Two layers are covered without a live database:

- Model metadata: the ``portfolio_constraint_set`` and
  ``portfolio_class_limits`` tables are registered with the expected columns,
  types, FK cascade, CHECK constraint and UNIQUE(portfolio_id, asset_class).
  These are offline inspections of ``Base.metadata`` (same style as
  test_optimize_jobs.py / test_models.py).
- CRUD service: ``upsert_constraints`` / ``get_constraints`` are exercised
  against a small in-memory fake AsyncSession that mimics the slice of
  AsyncSession the service uses (add/get/flush plus a tiny execute() that
  supports the header lookup and the class-limit delete/select). The contract
  asserted is the one Sprint B's save flow + CRUD endpoints depend on: upsert
  creates header+rows; a second upsert updates the header and replaces the
  rows (no duplicates); get returns the typed set; get(missing) -> None.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Float

# Importing Base triggers app.models.__init__, registering every ORM model.
from app.models import Base
from app.models.portfolio_constraint import (
    PortfolioClassLimit,
    PortfolioConstraintSet,
)
from app.services import portfolio_constraints as svc

# ---------------------------------------------------------------------------
# Fake AsyncSession — dict-backed stores for header (keyed by portfolio_id)
# and class-limit rows (a list). Mirrors only the operations the service uses.
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _ExecResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeAsyncSession:
    """Minimal async session backed by an in-memory model store.

    ``headers`` maps portfolio_id -> PortfolioConstraintSet. ``limits`` is a
    flat list of PortfolioClassLimit. ``execute`` interprets the statement by
    the entity it targets (header vs class-limit) and the operation
    (select/delete), which is all the service needs.
    """

    def __init__(self) -> None:
        self.headers: dict[int, PortfolioConstraintSet] = {}
        self.limits: list[PortfolioClassLimit] = []
        self._id_seq = 0

    def add(self, obj: Any) -> None:
        if isinstance(obj, PortfolioConstraintSet):
            self.headers[obj.portfolio_id] = obj
        elif isinstance(obj, PortfolioClassLimit):
            if obj.id is None:
                self._id_seq += 1
                obj.id = self._id_seq
            self.limits.append(obj)
        else:  # pragma: no cover - defensive
            raise TypeError(f"unexpected add: {type(obj)!r}")

    async def get(
        self, model: type, pk: Any
    ) -> PortfolioConstraintSet | None:
        if model is PortfolioConstraintSet:
            return self.headers.get(pk)
        raise NotImplementedError  # pragma: no cover

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def execute(self, statement: Any) -> _ExecResult:
        # Distinguish by the target entity recorded on the compiled statement.
        text = str(statement)
        is_limit = "portfolio_class_limits" in text
        if statement.is_delete:
            # Delete class-limit rows for the bound portfolio_id.
            pid = _extract_pid(statement)
            self.limits = [
                row for row in self.limits if row.portfolio_id != pid
            ]
            return _ExecResult([])
        # SELECT
        if is_limit:
            pid = _extract_pid(statement)
            rows = [r for r in self.limits if r.portfolio_id == pid]
            return _ExecResult(rows)
        # header select
        pid = _extract_pid(statement)
        hdr = self.headers.get(pid)
        return _ExecResult([hdr] if hdr is not None else [])


def _extract_pid(statement: Any) -> Any:
    """Pull the portfolio_id literal out of the statement's WHERE clause."""
    params = statement.compile().params
    for key, val in params.items():
        if "portfolio_id" in key:
            return val
    # Fallback: single bound param.
    vals = list(params.values())
    return vals[0] if vals else None


@pytest.fixture
def session() -> FakeAsyncSession:
    return FakeAsyncSession()


_PID = 42


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------


def test_constraint_tables_registered() -> None:
    assert "portfolio_constraint_set" in Base.metadata.tables
    assert "portfolio_class_limits" in Base.metadata.tables


def test_constraint_set_pk_is_portfolio_id() -> None:
    table = Base.metadata.tables["portfolio_constraint_set"]
    pk_cols = list(table.primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "portfolio_id"
    for col in ("cap", "min_weight", "overlap_cap"):
        assert isinstance(table.c[col].type, Float)
        assert table.c[col].nullable is True


def test_constraint_set_fk_cascade() -> None:
    table = Base.metadata.tables["portfolio_constraint_set"]
    fks = list(table.c["portfolio_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "portfolios"
    assert fks[0].ondelete == "CASCADE"


def test_class_limits_fk_cascade_and_unique() -> None:
    table = Base.metadata.tables["portfolio_class_limits"]
    fks = list(table.c["portfolio_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "portfolios"
    assert fks[0].ondelete == "CASCADE"
    uniques = {
        tuple(c.name for c in con.columns)
        for con in table.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("portfolio_id", "asset_class") in uniques


def test_class_limits_asset_class_check() -> None:
    table = Base.metadata.tables["portfolio_class_limits"]
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert "ck_portfolio_class_limits_asset_class" in checks


# ---------------------------------------------------------------------------
# CRUD service
# ---------------------------------------------------------------------------


async def test_upsert_creates_header_and_rows(
    session: FakeAsyncSession,
) -> None:
    await svc.upsert_constraints(
        session,
        _PID,
        cap=0.4,
        min_weight=0.01,
        overlap_cap=0.25,
        class_limits=[
            ("equity", 0.2, 0.6),
            ("fixed_income", 0.1, None),
        ],
    )
    assert _PID in session.headers
    hdr = session.headers[_PID]
    assert hdr.cap == 0.4
    assert hdr.min_weight == 0.01
    assert hdr.overlap_cap == 0.25
    rows = [r for r in session.limits if r.portfolio_id == _PID]
    assert len(rows) == 2
    classes = {r.asset_class for r in rows}
    assert classes == {"equity", "fixed_income"}


async def test_second_upsert_updates_header_and_replaces_rows(
    session: FakeAsyncSession,
) -> None:
    await svc.upsert_constraints(
        session,
        _PID,
        cap=0.4,
        min_weight=0.01,
        overlap_cap=0.25,
        class_limits=[("equity", 0.2, 0.6), ("fixed_income", 0.1, None)],
    )
    await svc.upsert_constraints(
        session,
        _PID,
        cap=0.5,
        min_weight=None,
        overlap_cap=None,
        class_limits=[("cash", 0.0, 0.1)],
    )
    hdr = session.headers[_PID]
    assert hdr.cap == 0.5
    assert hdr.min_weight is None
    assert hdr.overlap_cap is None
    rows = [r for r in session.limits if r.portfolio_id == _PID]
    assert len(rows) == 1
    assert rows[0].asset_class == "cash"


async def test_get_returns_typed_set(session: FakeAsyncSession) -> None:
    await svc.upsert_constraints(
        session,
        _PID,
        cap=0.4,
        min_weight=0.01,
        overlap_cap=0.25,
        class_limits=[("equity", 0.2, 0.6), ("alternatives", None, 0.15)],
    )
    result = await svc.get_constraints(session, _PID)
    assert result is not None
    assert result.cap == 0.4
    assert result.min_weight == 0.01
    assert result.overlap_cap == 0.25
    assert len(result.class_limits) == 2
    by_class = {cl.asset_class: cl for cl in result.class_limits}
    assert by_class["equity"].min_weight == 0.2
    assert by_class["equity"].max_weight == 0.6
    assert by_class["alternatives"].min_weight is None
    assert by_class["alternatives"].max_weight == 0.15


async def test_get_missing_returns_none(session: FakeAsyncSession) -> None:
    assert await svc.get_constraints(session, 999) is None
