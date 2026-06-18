"""Onda 0 - _market_weights_for supports mixed fund+equity baskets via market cap."""

import uuid

import numpy as np
import pytest

from app.optimizer import data as optimizer_data
from app.schemas.builder import EquityRefIn, FundRefIn
from app.services import portfolio_builder as pb

_FID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def test_mixed_basket_uses_aum_and_market_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = [FundRefIn(kind="fund", id=_FID), EquityRefIn(kind="equity", ticker="AAPL")]
    labels = [f"fund:{_FID}", "equity:AAPL"]

    async def fake_aum(session, fund_ids):
        return {_FID: 1_000_000_000.0}

    async def fake_mcap(session, tickers):
        return {"AAPL": 3_000_000_000.0}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_equity_market_cap", fake_mcap)

    w = await pb._market_weights_for(None, assets, labels)  # type: ignore[arg-type]
    # 1B / 4B = 0.25 (fund), 3B / 4B = 0.75 (equity); order matches `assets`.
    assert np.allclose(w, [0.25, 0.75])


async def test_equity_without_market_cap_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = [FundRefIn(kind="fund", id=_FID), EquityRefIn(kind="equity", ticker="ZZZZ")]
    labels = [f"fund:{_FID}", "equity:ZZZZ"]

    async def fake_aum(session, fund_ids):
        return {_FID: 1_000_000_000.0}

    async def fake_mcap(session, tickers):
        return {"ZZZZ": None}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_equity_market_cap", fake_mcap)

    with pytest.raises(pb.BuilderError, match="market weights require"):
        await pb._market_weights_for(None, assets, labels)  # type: ignore[arg-type]
