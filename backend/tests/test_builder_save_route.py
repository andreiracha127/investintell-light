"""Tests for POST /builder/save (app/api/routes/builder.py + builder_save).

Spot-price loaders and the CRUD persistence are stubbed at their canonical
modules — no live DB. The sizing math (weight → quantity) runs for real.

Covered: exact weight→quantity conversion, mixed fund+equity proposals, and
the 422 contract (asset without price, fund without ticker / unknown fund,
duplicate portfolio name, notional <= 0, weight that rounds to quantity 0).
"""

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.main import create_app
from app.schemas.portfolios import PortfolioCreate
from app.services import builder_save, portfolio_crud
from app.services.builder_save import FundSpot, position_for
from app.services.portfolio_builder import BuilderError

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_FUND_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_spots(
    monkeypatch: pytest.MonkeyPatch,
    equities: dict[str, float] | None = None,
    funds: dict[uuid.UUID, FundSpot] | None = None,
    classes: dict[uuid.UUID, dict[str, str | None]] | None = None,
) -> None:
    async def fake_equities(session: Any, tickers: list[str]) -> dict[str, float]:
        return {t: p for t, p in (equities or {}).items() if t in tickers}

    async def fake_funds(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, FundSpot]:
        return {i: s for i, s in (funds or {}).items() if i in fund_ids}

    async def fake_classes(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, str | None]]:
        return {i: c for i, c in (classes or {}).items() if i in fund_ids}

    monkeypatch.setattr(builder_save, "load_equity_spots", fake_equities)
    monkeypatch.setattr(builder_save, "load_fund_spots", fake_funds)
    monkeypatch.setattr(builder_save, "load_fund_classes", fake_classes)


def _stub_create(
    monkeypatch: pytest.MonkeyPatch,
    raise_duplicate: bool = False,
) -> tuple[list[PortfolioCreate], list[str]]:
    created: list[PortfolioCreate] = []
    origins: list[str] = []

    async def fake_create(
        session: Any,
        payload: PortfolioCreate,
        owner_sub: str,
        org_id: str | None,
        *,
        origin: str = "manual",
    ) -> SimpleNamespace:
        if raise_duplicate:
            raise portfolio_crud.DuplicatePortfolioNameError(
                f"A portfolio named {payload.name!r} already exists."
            )
        created.append(payload)
        origins.append(origin)
        return SimpleNamespace(id=7, name=payload.name, positions=payload.positions)

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    return created, origins


# ---------------------------------------------------------------------------
# Pure sizing math
# ---------------------------------------------------------------------------


def test_position_for_exact_quantity() -> None:
    # 0.25 * 1_000_000 / 100 = 2500 shares exactly.
    position = position_for("AAPL", 0.25, 100.0, 1_000_000)
    assert position.quantity == 2500.0
    assert position.acq_price == 100.0

    # 0.25 * 1_000_000 / 3 = 83333.3333... -> rounded to 4 decimals.
    position = position_for("XYZ", 0.25, 3.0, 1_000_000)
    assert position.quantity == 83333.3333

    # 0.1 * 50_000 / 451.23 = 11.08083... -> 11.0808
    position = position_for("VFIAX", 0.1, 451.23, 50_000)
    assert position.quantity == round(0.1 * 50_000 / 451.23, 4)


def test_position_for_quantity_rounding_to_zero_raises() -> None:
    # 1e-9 * 1_000_000 / 100 = 1e-5 -> rounds to 0.0000 at 4 decimals.
    with pytest.raises(BuilderError, match="quantidade 0"):
        position_for("DUST", 1e-9, 100.0, 1_000_000)


def test_position_for_non_positive_price_raises() -> None:
    with pytest.raises(BuilderError, match="sem preço"):
        position_for("BAD", 0.5, 0.0, 1_000_000)


# ---------------------------------------------------------------------------
# Route: happy path (mixed fund + equity)
# ---------------------------------------------------------------------------


async def test_save_mixed_fund_and_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(
        monkeypatch,
        equities={"AAPL": 200.0},
        funds={_FUND_ID: FundSpot(ticker="VFIAX", name="Vanguard 500", nav=450.0)},
    )
    created, origins = _stub_create(monkeypatch)
    payload = {
        "name": "Builder min_cvar 2026-06-11",
        "weights": [
            {"asset": {"kind": "fund", "id": str(_FUND_ID)}, "weight": 0.6},
            {"asset": {"kind": "equity", "ticker": "aapl"}, "weight": 0.4},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["portfolio_id"] == 7
    assert body["name"] == "Builder min_cvar 2026-06-11"
    assert body["notional_usd"] == 1_000_000  # default
    by_ticker = {p["ticker"]: p for p in body["positions"]}
    # 0.6 * 1_000_000 / 450 = 1333.3333...; 0.4 * 1_000_000 / 200 = 2000.
    assert by_ticker["VFIAX"]["quantity"] == round(600_000 / 450.0, 4)
    assert by_ticker["VFIAX"]["price"] == 450.0
    assert by_ticker["AAPL"]["quantity"] == 2000.0
    assert by_ticker["AAPL"]["price"] == 200.0
    # No fills — both positions are reference; cost basis == reference price.
    assert by_ticker["VFIAX"]["basis"] == "reference"
    assert by_ticker["AAPL"]["basis"] == "reference"
    assert by_ticker["AAPL"]["cost_basis"] == 200.0
    # Fixed disclaimer (F8.6b).
    assert "series NAV" in body["pricing_note"]

    # Persisted payload: cash 0, cost basis = spot price, origin = builder.
    (persisted,) = created
    assert origins == ["builder"]
    assert persisted.cash == 0.0
    persisted_by_ticker = {p.ticker: p for p in persisted.positions}
    assert persisted_by_ticker["VFIAX"].acq_price == 450.0
    assert persisted_by_ticker["VFIAX"].basis == "reference"
    assert persisted_by_ticker["AAPL"].acq_price == 200.0
    assert persisted_by_ticker["AAPL"].quantity == 2000.0
    assert persisted_by_ticker["AAPL"].commission is None


async def test_save_custom_notional(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(monkeypatch, equities={"AAPL": 200.0, "MSFT": 400.0})
    _stub_create(monkeypatch)
    payload = {
        "name": "Custom notional",
        "notional_usd": 50_000,
        "weights": [
            {"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 0.5},
            {"asset": {"kind": "equity", "ticker": "MSFT"}, "weight": 0.5},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 201, response.text
    by_ticker = {p["ticker"]: p for p in response.json()["positions"]}
    assert by_ticker["AAPL"]["quantity"] == 125.0  # 25_000 / 200
    assert by_ticker["MSFT"]["quantity"] == 62.5  # 25_000 / 400


# ---------------------------------------------------------------------------
# Route: 422 contract
# ---------------------------------------------------------------------------


async def test_save_equity_without_price_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(monkeypatch, equities={})
    _stub_create(monkeypatch)
    payload = {
        "name": "No price",
        "weights": [{"asset": {"kind": "equity", "ticker": "GHOST"}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    assert "sem preço para equity:GHOST" in response.json()["detail"]


async def test_save_fund_without_ticker_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(
        monkeypatch,
        funds={_FUND_ID: FundSpot(ticker=None, name="No Ticker Fund", nav=10.0)},
    )
    _stub_create(monkeypatch)
    payload = {
        "name": "No ticker",
        "weights": [{"asset": {"kind": "fund", "id": str(_FUND_ID)}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "não tem ticker" in detail and "No Ticker Fund" in detail


async def test_save_fund_without_nav_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(
        monkeypatch,
        funds={_FUND_ID: FundSpot(ticker="VFIAX", name="Vanguard 500", nav=None)},
    )
    _stub_create(monkeypatch)
    payload = {
        "name": "No NAV",
        "weights": [{"asset": {"kind": "fund", "id": str(_FUND_ID)}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    assert f"sem preço para fund:{_FUND_ID}" in response.json()["detail"]


async def test_save_unknown_fund_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(monkeypatch)
    _stub_create(monkeypatch)
    payload = {
        "name": "Unknown fund",
        "weights": [{"asset": {"kind": "fund", "id": str(_FUND_ID_2)}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    assert "fundo desconhecido" in response.json()["detail"]


async def test_save_duplicate_name_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_spots(monkeypatch, equities={"AAPL": 200.0})
    _stub_create(monkeypatch, raise_duplicate=True)
    payload = {
        "name": "Dup",
        "weights": [{"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    assert "already exists" in response.json()["detail"]


async def test_save_duplicate_resolved_ticker_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fund whose ticker collides with an equity in the same proposal is a
    422 — positions are keyed by ticker, two rows would conflict."""
    _stub_spots(
        monkeypatch,
        equities={"SPY": 500.0},
        funds={_FUND_ID: FundSpot(ticker="SPY", name="SPDR S&P 500", nav=499.0)},
    )
    _stub_create(monkeypatch)
    payload = {
        "name": "Collision",
        "weights": [
            {"asset": {"kind": "fund", "id": str(_FUND_ID)}, "weight": 0.5},
            {"asset": {"kind": "equity", "ticker": "SPY"}, "weight": 0.5},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    assert "duplicados" in response.json()["detail"]


@pytest.mark.parametrize("notional", [0, -1000])
async def test_save_non_positive_notional_422(
    monkeypatch: pytest.MonkeyPatch, notional: float
) -> None:
    _stub_spots(monkeypatch, equities={"AAPL": 200.0})
    _stub_create(monkeypatch)
    payload = {
        "name": "Bad notional",
        "notional_usd": notional,
        "weights": [{"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422  # Pydantic: notional_usd must be > 0


async def test_save_zero_weight_422() -> None:
    payload = {
        "name": "Zero weight",
        "weights": [{"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422  # Pydantic: weight must be > 0


# ---------------------------------------------------------------------------
# F8.6b: executed fills + fund classes
# ---------------------------------------------------------------------------


def test_executed_cost_basis_exact() -> None:
    # fill 100, qty 10, commission 5 => (100*10 + 5)/10 = 100.5
    assert builder_save.executed_cost_basis(100.0, 10.0, 5.0) == 100.5
    # commission None counts as 0.
    assert builder_save.executed_cost_basis(100.0, 10.0, None) == 100.0
    # rounding to 6 decimals: (3*7 + 1)/7 = 3.142857142857...
    assert builder_save.executed_cost_basis(3.0, 7.0, 1.0) == round(22 / 7, 6)


def test_position_for_executed_fill() -> None:
    # weight 0.1 * notional 10_000 / fill 100 = qty 10; commission 5 => 100.5.
    position = position_for(
        "AAPL", 0.1, 99.0, 10_000, fill_price=100.0, commission=5.0,
        trade_date=dt.date(2026, 6, 10),
    )
    assert position.quantity == 10.0
    assert position.acq_price == 100.5
    assert position.basis == "executed"
    assert position.commission == 5.0
    assert position.trade_date == dt.date(2026, 6, 10)


def test_position_for_reference_default() -> None:
    position = position_for("AAPL", 0.25, 100.0, 1_000_000)
    assert position.basis == "reference"
    assert position.commission is None
    assert position.trade_date is None


async def test_save_executed_fill_cost_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fill sizes the position; commission lands in the cost basis."""
    _stub_spots(monkeypatch, equities={"AAPL": 99.0, "MSFT": 400.0})
    created, _origins = _stub_create(monkeypatch)
    payload = {
        "name": "Executed",
        "notional_usd": 10_000,
        "weights": [
            {
                "asset": {"kind": "equity", "ticker": "AAPL"},
                "weight": 0.1,
                "fill_price": 100.0,
                "commission": 5.0,
                "trade_date": "2026-06-10",
            },
            {"asset": {"kind": "equity", "ticker": "MSFT"}, "weight": 0.9},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 201, response.text
    by_ticker = {p["ticker"]: p for p in response.json()["positions"]}
    # qty = 0.1 * 10_000 / 100 (the FILL, not the 99.0 reference) = 10.
    assert by_ticker["AAPL"]["quantity"] == 10.0
    assert by_ticker["AAPL"]["price"] == 100.0
    assert by_ticker["AAPL"]["basis"] == "executed"
    assert by_ticker["AAPL"]["cost_basis"] == 100.5  # (100*10 + 5)/10
    assert by_ticker["MSFT"]["basis"] == "reference"
    assert by_ticker["MSFT"]["cost_basis"] == 400.0

    (persisted,) = created
    aapl = {p.ticker: p for p in persisted.positions}["AAPL"]
    assert aapl.acq_price == 100.5
    assert aapl.basis == "executed"
    assert aapl.commission == 5.0
    assert aapl.trade_date == dt.date(2026, 6, 10)


async def test_save_commission_without_fill_price_422() -> None:
    payload = {
        "name": "Bad commission",
        "weights": [
            {
                "asset": {"kind": "equity", "ticker": "AAPL"},
                "weight": 1.0,
                "commission": 5.0,
            }
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)
    assert response.status_code == 422


async def test_save_class_ticker_on_equity_422() -> None:
    payload = {
        "name": "Class on equity",
        "weights": [
            {
                "asset": {"kind": "equity", "ticker": "AAPL"},
                "weight": 1.0,
                "class_ticker": "RGAGX",
            }
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)
    assert response.status_code == 422


async def test_save_fund_class_ticker_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid class_ticker keys the position by the CLASS ticker, priced
    with the series NAV (proxy)."""
    _stub_spots(
        monkeypatch,
        funds={_FUND_ID: FundSpot(ticker="AGTHX", name="Growth Fund", nav=80.0)},
        classes={_FUND_ID: {"RGAGX": "Class R-6", "AGTHX": "Class A"}},
    )
    created, _origins = _stub_create(monkeypatch)
    payload = {
        "name": "Class pick",
        "notional_usd": 8_000,
        "weights": [
            {
                "asset": {"kind": "fund", "id": str(_FUND_ID)},
                "weight": 1.0,
                "class_ticker": "rgagx",
            }
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 201, response.text
    (position,) = response.json()["positions"]
    assert position["ticker"] == "RGAGX"  # the class, not the representative
    assert position["quantity"] == 100.0  # 8_000 / 80 (series NAV proxy)
    assert position["price"] == 80.0
    assert position["basis"] == "reference"
    (persisted,) = created
    assert persisted.positions[0].ticker == "RGAGX"
    assert persisted.positions[0].acq_price == 80.0


async def test_save_fund_class_ticker_invalid_422_lists_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_spots(
        monkeypatch,
        funds={_FUND_ID: FundSpot(ticker="AGTHX", name="Growth Fund", nav=80.0)},
        classes={_FUND_ID: {"RGAGX": "Class R-6", "RGABX": "Class B"}},
    )
    _stub_create(monkeypatch)
    payload = {
        "name": "Wrong class",
        "weights": [
            {
                "asset": {"kind": "fund", "id": str(_FUND_ID)},
                "weight": 1.0,
                "class_ticker": "WRONGX",
            }
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "WRONGX" in detail
    assert "RGABX, RGAGX" in detail  # valid classes listed, sorted


async def test_save_fund_class_ticker_executed_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Class pick combined with an executed fill: class keys the row, the
    fill + commission define the cost basis."""
    _stub_spots(
        monkeypatch,
        funds={_FUND_ID: FundSpot(ticker="AGTHX", name="Growth Fund", nav=80.0)},
        classes={_FUND_ID: {"RGAGX": "Class R-6"}},
    )
    _stub_create(monkeypatch)
    payload = {
        "name": "Class executed",
        "notional_usd": 1_000,
        "weights": [
            {
                "asset": {"kind": "fund", "id": str(_FUND_ID)},
                "weight": 1.0,
                "class_ticker": "RGAGX",
                "fill_price": 100.0,
                "commission": 5.0,
            }
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 201, response.text
    (position,) = response.json()["positions"]
    assert position["ticker"] == "RGAGX"
    assert position["quantity"] == 10.0  # 1_000 / 100 (the fill)
    assert position["basis"] == "executed"
    assert position["cost_basis"] == 100.5


async def test_save_blank_name_422() -> None:
    payload = {
        "name": "   ",
        "weights": [{"asset": {"kind": "equity", "ticker": "AAPL"}, "weight": 1.0}],
    }
    async with _client() as client:
        response = await client.post("/builder/save", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Wiring: owner identity forwarded from route to run_save
# ---------------------------------------------------------------------------


async def test_save_forwards_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str | None]] = []

    async def fake_run_save(session, payload, owner_sub, org_id):
        captured.append((owner_sub, org_id))
        from app.schemas.builder import SaveResponse

        return SaveResponse(portfolio_id=1, name="P", notional_usd=1000.0, positions=[])

    monkeypatch.setattr(builder_save, "run_save", fake_run_save)
    payload = {
        "name": "Builder min_cvar 2026-06-11",
        "weights": [
            {"asset": {"kind": "fund", "id": str(_FUND_ID)}, "weight": 0.6},
            {"asset": {"kind": "equity", "ticker": "aapl"}, "weight": 0.4},
        ],
    }
    async with _client() as ac:
        await ac.post("/builder/save", json=payload)
    assert captured == [("u-1", None)]
