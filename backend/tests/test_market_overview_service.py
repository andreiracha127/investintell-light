"""Tests do ranking puro do market overview (sem DB)."""

import datetime as dt

import pytest

from app.services.market_overview import (
    MIN_DOLLAR_VOLUME,
    PRICE_FLOOR,
    OverviewRow,
    rank_overview,
)

AS_OF = dt.date(2026, 6, 11)


def _row(ticker: str, last: float, prev: float, *, volume: int = 10_000_000,
         high: float | None = None, low: float | None = None,
         sector: str | None = "Information Technology") -> OverviewRow:
    return OverviewRow(
        ticker=ticker, name=f"{ticker} Inc", sector=sector,
        last=last, prev=prev, volume=volume,
        high_52w=high if high is not None else max(last, prev) * 1.3,
        low_52w=low if low is not None else min(last, prev) * 0.7,
        as_of=AS_OF,
    )


def test_gainers_losers_sorted_by_change_pct() -> None:
    rows = [_row("UP9", 109, 100), _row("UP5", 105, 100), _row("DN7", 93, 100)]
    out = rank_overview(rows)
    assert [r.ticker for r in out["gainers"][:2]] == ["UP9", "UP5"]
    assert out["losers"][0].ticker == "DN7"
    assert out["gainers"][0].change_pct == pytest.approx(0.09)
    assert out["as_of"] == AS_OF


def test_liquidity_floor_excludes_penny_and_thin_volume() -> None:
    rows = [
        _row("PENNY", 4.40, 4.00),                       # < PRICE_FLOOR
        _row("THIN", 200.0, 100.0, volume=1_000),        # dollar vol < MIN_DOLLAR_VOLUME
        _row("OK", 101.0, 100.0),
    ]
    out = rank_overview(rows)
    tickers = {r.ticker for r in out["gainers"]}
    assert tickers == {"OK"}
    assert PRICE_FLOOR == 5.0 and MIN_DOLLAR_VOLUME == 5_000_000.0


def test_most_active_ranked_by_dollar_volume() -> None:
    rows = [
        _row("BIG", 100.0, 100.0, volume=50_000_000),
        _row("MID", 100.0, 100.0, volume=20_000_000),
    ]
    out = rank_overview(rows)
    assert [r.ticker for r in out["most_active"]] == ["BIG", "MID"]


def test_52w_lists_rank_by_proximity_to_extreme() -> None:
    rows = [
        _row("ATHI", 130.0, 128.0, high=130.0, low=80.0),   # no topo
        _row("NEAR", 127.0, 126.0, high=130.0, low=80.0),   # perto
        _row("ATLO", 80.0, 81.0, high=130.0, low=80.0),     # no fundo
        _row("MID", 100.0, 100.0, high=130.0, low=80.0),    # longe de ambos
    ]
    out = rank_overview(rows)
    highs = [r.ticker for r in out["highs_52w"]]
    lows = [r.ticker for r in out["lows_52w"]]
    assert highs[0] == "ATHI" and "ATLO" not in highs
    assert lows[0] == "ATLO" and "ATHI" not in lows
    assert "MID" not in highs and "MID" not in lows  # fora da janela de 2%


def test_sectors_median_and_null_sector_ignored() -> None:
    rows = [
        _row("A", 102, 100, sector="Energy"),
        _row("B", 104, 100, sector="Energy"),
        _row("C", 106, 100, sector="Energy"),
        _row("D", 99, 100, sector=None),
    ]
    out = rank_overview(rows)
    assert len(out["sectors"]) == 1
    sec = out["sectors"][0]
    assert sec.sector == "Energy" and sec.n == 3
    assert sec.change_pct_median == pytest.approx(0.04)


def test_breadth_counts_ratio_highs_lows_and_up_volume() -> None:
    rows = [
        _row("UP1", 110.0, 100.0, volume=30_000_000, high=110.0, low=60.0),  # advancing + new high
        _row("UP2", 105.0, 100.0, volume=10_000_000, high=130.0, low=60.0),  # advancing
        _row("DN1", 80.0, 100.0, volume=20_000_000, high=130.0, low=80.0),   # declining + new low
        _row("FLAT", 100.0, 100.0, volume=5_000_000, high=130.0, low=60.0),  # unchanged
    ]
    out = rank_overview(rows)
    b = out["breadth"]
    assert b is not None
    assert (b.tracked, b.advancing, b.declining, b.unchanged) == (4, 2, 1, 1)
    assert b.advance_decline_ratio == pytest.approx(2.0)
    assert b.new_highs_52w == 1 and b.new_lows_52w == 1
    # up-volume = (30M + 10M) advancing / 65M total
    assert b.up_volume_share == pytest.approx(40_000_000 / 65_000_000)


def test_breadth_ratio_with_zero_decliners_is_advancing_count() -> None:
    out = rank_overview([_row("UP1", 110.0, 100.0), _row("UP2", 105.0, 100.0)])
    b = out["breadth"]
    assert b is not None and b.declining == 0
    assert b.advance_decline_ratio == pytest.approx(2.0)


def test_empty_rows_yield_empty_overview() -> None:
    out = rank_overview([])
    assert out["as_of"] is None
    assert out["gainers"] == [] and out["sectors"] == []
    assert out["breadth"] is None
