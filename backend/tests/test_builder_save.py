"""Unit/integration tests for builder_save.run_save persistence (Sprint B, Task 5).

The route tests (test_builder_save_route.py) stub the three DB-backed
persistence steps. Here we run the REAL persistence functions
(``_seed_inception_ledger``, ``portfolio_ledger.materialize_portfolio_nav``,
``portfolio_constraints.upsert_constraints`` / ``get_constraints``) against a
small in-memory fake AsyncSession, so we can assert that after a save:

- ``portfolio_nav_daily`` gets >= 1 materialized row (NAV synthesized from the
  seeded inception ledger, priced at the inception trade), and
- ``get_constraints`` returns exactly the persisted set (cap / overlap_cap /
  per-class limits).

Reads that would need full SQL (the portfolio header, the ledger list, and the
price history) are stubbed at their service boundaries; everything the service
layer actually writes (ledger rows, NAV rows, constraint header + class rows)
flows through the fake session and is asserted from there.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.models.portfolio import (
    PortfolioNavDaily,
    PortfolioTransaction,
)
from app.models.portfolio_constraint import (
    PortfolioClassLimit,
    PortfolioConstraintSet,
)
from app.schemas.builder import SaveRequest
from app.services import (
    builder_save,
    portfolio_constraints,
    portfolio_crud,
    portfolio_ledger,
)

_INCEPTION = dt.date(2026, 1, 15)


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _ExecResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)


class FakeSession:
    """In-memory async session covering the writes run_save's persistence does.

    Stores the constraint header (keyed by portfolio_id), the class-limit rows,
    the seeded ledger transactions and the materialized NAV rows. ``execute``
    dispatches on the targeted entity for the delete/select statements the
    services emit.
    """

    def __init__(self) -> None:
        self.headers: dict[int, PortfolioConstraintSet] = {}
        self.class_limits: list[PortfolioClassLimit] = []
        self.transactions: list[PortfolioTransaction] = []
        self.nav_rows: list[PortfolioNavDaily] = []

    def add(self, obj: Any) -> None:
        if isinstance(obj, PortfolioConstraintSet):
            self.headers[obj.portfolio_id] = obj
        elif isinstance(obj, PortfolioClassLimit):
            self.class_limits.append(obj)
        elif isinstance(obj, PortfolioTransaction):
            self.transactions.append(obj)
        elif isinstance(obj, PortfolioNavDaily):
            self.nav_rows.append(obj)
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected add(): {obj!r}")

    def add_all(self, objs: Any) -> None:
        for obj in objs:
            self.add(obj)

    async def get(self, entity: Any, pk: Any) -> Any:
        if entity is PortfolioConstraintSet:
            return self.headers.get(pk)
        raise AssertionError(f"unexpected get(): {entity!r}")  # pragma: no cover

    async def execute(self, stmt: Any) -> _ExecResult:
        entity = _stmt_entity(stmt)
        is_delete = stmt.__class__.__name__ == "Delete"
        if entity is PortfolioNavDaily:
            if is_delete:
                self.nav_rows.clear()
            return _ExecResult([])
        if entity is PortfolioClassLimit:
            if is_delete:
                self.class_limits.clear()
                return _ExecResult([])
            return _ExecResult(sorted(self.class_limits, key=lambda r: r.asset_class))
        raise AssertionError(f"unexpected execute(): {entity!r}")  # pragma: no cover

    async def flush(self) -> None:
        return None


def _stmt_entity(stmt: Any) -> Any:
    """Best-effort: recover the ORM entity a delete/select statement targets."""
    table = None
    if stmt.__class__.__name__ == "Delete":
        table = stmt.table
    else:  # Select
        froms = stmt.get_final_froms()
        table = froms[0] if froms else None
    name = getattr(table, "name", None)
    for entity in (PortfolioNavDaily, PortfolioClassLimit, PortfolioConstraintSet):
        if entity.__tablename__ == name:
            return entity
    return None  # pragma: no cover


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


def _stub_reads(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    """Stub the spot loaders + the ledger read helpers materialize_portfolio_nav
    needs (header lookup, ledger list, price history), leaving the persistence
    writes to flow through the fake session and the NAV math to run for real."""

    async def fake_equities(_session: Any, tickers: list[str]) -> dict[str, float]:
        return {t: 100.0 for t in tickers}

    async def fake_funds(_session: Any, fund_ids: list[Any]) -> dict[Any, Any]:
        return {}

    async def fake_classes(_session: Any, fund_ids: list[Any]) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(builder_save, "load_equity_spots", fake_equities)
    monkeypatch.setattr(builder_save, "load_fund_spots", fake_funds)
    monkeypatch.setattr(builder_save, "load_fund_classes", fake_classes)

    async def fake_create(
        _session: Any,
        payload: Any,
        owner_sub: str,
        org_id: str | None,
        *,
        origin: str = "manual",
    ) -> Any:
        # The portfolio "exists" with the requested inception date; positions are
        # not needed by the persistence path under test.
        from types import SimpleNamespace

        assert (owner_sub, org_id, origin) == ("u-1", None, "builder")
        return SimpleNamespace(
            id=42, name=payload.name, inception_date=payload.inception_date
        )

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)

    async def fake_get_portfolio(
        _session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(id=portfolio_id, inception_date=_INCEPTION)

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)

    async def fake_list_transactions(
        _session: Any, portfolio_id: int
    ) -> list[PortfolioTransaction]:
        return list(session.transactions)

    monkeypatch.setattr(portfolio_ledger, "list_transactions", fake_list_transactions)

    async def fake_price_history(
        _session: Any, tickers: Any, start: Any, end: Any
    ) -> dict[str, list[tuple[dt.date, float]]]:
        # No EOD/NAV history beyond the inception trade — the NAV builder still
        # prices the trade-date point from the transaction itself.
        return {}

    monkeypatch.setattr(portfolio_ledger, "load_price_history", fake_price_history)


async def test_run_save_materializes_nav_and_persists_constraints(
    monkeypatch: pytest.MonkeyPatch, session: FakeSession
) -> None:
    _stub_reads(monkeypatch, session)
    payload = SaveRequest.model_validate(
        {
            "name": "Constrained",
            "inception_date": "2026-01-15",
            "weights": [
                {"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 1.0}
            ],
            "constraints": {
                "cap": 0.3,
                "overlap_cap": 0.1,
                "block_budgets": [
                    {"asset_class": "equity", "lo": 0.2, "hi": 0.8},
                ],
            },
        }
    )

    response = await builder_save.run_save(
        session, payload, "u-1", None
    )  # type: ignore[arg-type]
    assert response.portfolio_id == 42

    # (c) NAV materialized: at least one portfolio_nav_daily row, dated at the
    # inception trade.
    assert len(session.nav_rows) >= 1
    assert session.nav_rows[0].nav_date == _INCEPTION
    assert session.nav_rows[0].nav > 0

    # one inception buy per position in the ledger.
    assert [t.ticker for t in session.transactions] == ["AAPL"]
    assert session.transactions[0].side == "buy"
    assert session.transactions[0].trade_date == _INCEPTION

    # (a) constraints round-trip through get_constraints.
    persisted = await portfolio_constraints.get_constraints(session, 42)  # type: ignore[arg-type]
    assert persisted is not None
    assert persisted.cap == 0.3
    assert persisted.overlap_cap == 0.1
    assert [(c.asset_class, c.min_weight, c.max_weight) for c in persisted.class_limits] == [
        ("equity", 0.2, 0.8),
    ]


async def test_run_save_without_constraints_still_materializes_nav(
    monkeypatch: pytest.MonkeyPatch, session: FakeSession
) -> None:
    """(d) Back-compat: no constraints -> no header persisted, NAV still built."""
    _stub_reads(monkeypatch, session)
    payload = SaveRequest.model_validate(
        {
            "name": "Plain",
            "weights": [
                {"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 1.0}
            ],
        }
    )

    response = await builder_save.run_save(
        session, payload, "u-1", None
    )  # type: ignore[arg-type]
    assert response.portfolio_id == 42
    assert len(session.nav_rows) >= 1
    assert await portfolio_constraints.get_constraints(session, 42) is None  # type: ignore[arg-type]
