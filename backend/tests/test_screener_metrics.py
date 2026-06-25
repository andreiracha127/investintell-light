"""Tests for the screener metrics snapshot job (app/sync/metrics.py).

No live network, no live DB: compute_ticker_metrics is exercised on
synthetic hand-checkable frames; upserts are checked by compiling against
the PostgreSQL dialect; run_metrics' batching shape runs against a fake
session. Also covers the shared chunked() helper (app/core/chunks.py).
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from app.analytics import annualized_volatility, simple_returns
from app.core.chunks import chunked
from app.sync import metrics as metrics_mod
from app.sync.metrics import (
    BENCHMARK_TICKERS,
    METRIC_COLUMNS,
    build_metrics_upsert,
    compute_ticker_metrics,
    group_price_rows,
    run_metrics,
)

_AS_OF = dt.date(2026, 6, 10)  # a Wednesday
_NOW = dt.datetime(2026, 6, 11, 12, 0, tzinfo=dt.UTC)

# ---------------------------------------------------------------------------
# Synthetic frame builders
# ---------------------------------------------------------------------------


def _frame(adj_close: pd.Series, volume: float = 1000.0) -> pd.DataFrame:
    """Price frame with close == adj_close and constant volume."""
    return pd.DataFrame(
        {
            "adj_close": adj_close.to_numpy(dtype=float),
            "close": adj_close.to_numpy(dtype=float),
            "volume": [volume] * len(adj_close),
        },
        index=adj_close.index,
    )


def _flat_then_jump(periods: int, base: float = 100.0, last: float = 110.0) -> pd.DataFrame:
    """*periods* business days ending at as_of: constant *base*, last day *last*."""
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=periods)
    values = [base] * (periods - 1) + [last]
    return _frame(pd.Series(values, index=index))


def _no_benchmarks() -> dict[str, pd.Series]:
    return {}


def _fund_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "period_end": dt.date(2026, 3, 31),
        "book_equity": 200.0,
        "total_assets": 1000.0,
        "net_income_ttm": 50.0,
        "revenue": 400.0,
        "gross_profit": 100.0,
        "shares_outstanding": 10.0,
        "quality_roa": 0.07,
        "investment_growth": 0.03,
        "profitability_gross": 0.25,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# compute_ticker_metrics — trailing and calendar returns
# ---------------------------------------------------------------------------


def test_trailing_returns_hand_checked() -> None:
    """Constant 100 then a final 110: every covered window returns exactly 10%."""
    # 400 business days ≈ 553 calendar days — covers everything through 1y.
    out = compute_ticker_metrics(_flat_then_jump(400), _no_benchmarks(), None, _AS_OF)
    for col in ("ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_ytd", "ret_mtd"):
        assert out[col] == pytest.approx(0.10), col


def test_returns_emit_all_metric_columns() -> None:
    out = compute_ticker_metrics(_flat_then_jump(400), _no_benchmarks(), None, _AS_OF)
    assert set(out) == set(METRIC_COLUMNS)


def test_ytd_and_mtd_use_calendar_boundaries() -> None:
    """Series crossing Jan 1: 100 in 2025, 120 Jan-May 2026, 126 in June."""
    index = pd.bdate_range(start="2025-12-01", end=pd.Timestamp(_AS_OF))
    values = [
        100.0 if ts.year == 2025 else (126.0 if ts.month == 6 else 120.0)
        for ts in index
    ]
    out = compute_ticker_metrics(
        _frame(pd.Series(values, index=index)), _no_benchmarks(), None, _AS_OF
    )
    # YTD base = last close of 2025 (100); MTD base = last close of May (120).
    assert out["ret_ytd"] == pytest.approx(0.26)
    assert out["ret_mtd"] == pytest.approx(126.0 / 120.0 - 1.0)


def test_ytd_null_when_history_starts_after_jan_1() -> None:
    out = compute_ticker_metrics(_flat_then_jump(30), _no_benchmarks(), None, _AS_OF)
    assert out["ret_ytd"] is None
    assert out["ret_mtd"] is not None  # 30 bdays reach back before June 1


# ---------------------------------------------------------------------------
# compute_ticker_metrics — volatility matches the engine
# ---------------------------------------------------------------------------


def test_vol_1m_matches_engine_on_explicit_slice() -> None:
    """vol_1m must equal the engine vol on prices from the 1m base observation.

    as_of − 1 month = 2026-05-10 (a Sunday) → base = Friday 2026-05-08, so the
    expected slice is prices.loc['2026-05-08':] — stated explicitly here.
    """
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=120)
    # Deterministic wiggle so the vol is nonzero.
    values = [100.0 + (i % 7) for i in range(120)]
    prices = pd.Series(values, index=index)
    out = compute_ticker_metrics(_frame(prices), _no_benchmarks(), None, _AS_OF)
    expected = annualized_volatility(
        simple_returns(prices.loc[pd.Timestamp("2026-05-08") :])
    )
    assert out["vol_1m"] == pytest.approx(expected)
    assert out["vol_3m"] == pytest.approx(
        annualized_volatility(simple_returns(prices.loc[pd.Timestamp("2026-03-10") :]))
    )


# ---------------------------------------------------------------------------
# compute_ticker_metrics — beta and correlation vs synthetic benchmarks
# ---------------------------------------------------------------------------


def _synthetic_spy_and_2x_asset() -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """SPY alternates ±1% daily; the asset moves exactly 2x SPY each day."""
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=600)  # ≈ 2.3 years
    spy_rets = pd.Series([0.01 if i % 2 == 0 else -0.01 for i in range(600)], index=index)
    spy_prices = 100.0 * (1.0 + spy_rets).cumprod()
    asset_prices = 100.0 * (1.0 + 2.0 * spy_rets).cumprod()
    benchmark_map = {"SPY": simple_returns(spy_prices)}
    return benchmark_map, _frame(asset_prices)


def test_beta_of_2x_series_is_2_for_every_window() -> None:
    benchmark_map, frame = _synthetic_spy_and_2x_asset()
    out = compute_ticker_metrics(frame, benchmark_map, None, _AS_OF)
    for col in ("beta_3m_spy", "beta_6m_spy", "beta_1y_spy", "beta_2y_spy"):
        assert out[col] == pytest.approx(2.0, abs=1e-9), col


def test_corr_of_scaled_series_is_1_and_missing_benchmarks_are_null() -> None:
    benchmark_map, frame = _synthetic_spy_and_2x_asset()
    out = compute_ticker_metrics(frame, benchmark_map, None, _AS_OF)
    assert out["corr_spy"] == pytest.approx(1.0)
    # GLD/AGG/TLT/USO absent from the map → those metrics are NULL.
    for col in ("corr_gld", "corr_agg", "corr_tlt", "corr_uso"):
        assert out[col] is None, col


def test_beta_null_when_benchmark_variance_is_zero() -> None:
    """A flat benchmark makes beta undefined — NULL, not an exception."""
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=600)
    flat = pd.Series([100.0] * 600, index=index)
    benchmark_map = {"SPY": simple_returns(flat)}
    out = compute_ticker_metrics(_flat_then_jump(600), benchmark_map, None, _AS_OF)
    assert out["beta_1y_spy"] is None


# ---------------------------------------------------------------------------
# compute_ticker_metrics — SMA distance
# ---------------------------------------------------------------------------


def test_pct_above_sma_signs_and_value() -> None:
    rising = _frame(
        pd.Series(
            [float(100 + i) for i in range(250)],
            index=pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=250),
        )
    )
    falling = _frame(
        pd.Series(
            [float(500 - i) for i in range(250)],
            index=pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=250),
        )
    )
    up = compute_ticker_metrics(rising, _no_benchmarks(), None, _AS_OF)
    down = compute_ticker_metrics(falling, _no_benchmarks(), None, _AS_OF)
    for col in ("pct_above_sma20", "pct_above_sma50", "pct_above_sma200"):
        assert up[col] is not None and up[col] > 0, col
        assert down[col] is not None and down[col] < 0, col
    # Hand-check sma20 on the rising series: last 20 closes are 330..349,
    # SMA = 339.5, close = 349.
    assert up["pct_above_sma20"] == pytest.approx(349.0 / 339.5 - 1.0)


# ---------------------------------------------------------------------------
# compute_ticker_metrics — short history yields exactly the right NULLs
# ---------------------------------------------------------------------------


def test_short_history_nulls_exactly_the_uncovered_windows() -> None:
    """30 business days (~6 calendar weeks): 1w/1m windows covered, rest NULL."""
    out = compute_ticker_metrics(_flat_then_jump(30), _no_benchmarks(), None, _AS_OF)

    present = ("ret_1w", "ret_1m", "ret_mtd", "vol_1m", "pct_above_sma20",
               "price_close", "avg_volume_1m")
    absent = ("ret_3m", "ret_6m", "ret_1y", "ret_ytd",
              "vol_3m", "vol_6m", "vol_1y",
              "beta_3m_spy", "beta_6m_spy", "beta_1y_spy", "beta_2y_spy",
              "corr_spy", "corr_gld", "corr_agg", "corr_tlt", "corr_uso",
              "pct_above_sma50", "pct_above_sma200")
    for col in present:
        assert out[col] is not None, col
    for col in absent:
        assert out[col] is None, col


def test_single_row_history_yields_levels_only() -> None:
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=1)
    out = compute_ticker_metrics(
        _frame(pd.Series([42.0], index=index), volume=777.0),
        _no_benchmarks(),
        None,
        _AS_OF,
    )
    assert out["price_close"] == pytest.approx(42.0)
    assert out["avg_volume_1m"] == pytest.approx(777.0)
    for col in METRIC_COLUMNS:
        if col not in ("price_close", "avg_volume_1m"):
            assert out[col] is None, col


def test_avg_volume_1m_nan_guard_yields_none() -> None:
    """F6.3 review: avg_volume_1m guard — NaN mean → None (fail-soft parity).

    Inject NaN into the volume column to verify the guard fires and returns
    None rather than propagating a float NaN into the snapshot.
    """
    _nan = float("nan")
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=5)
    frame = pd.DataFrame(
        {
            "adj_close": [100.0] * 5,
            "close": [100.0] * 5,
            "volume": [_nan] * 5,  # all NaN → mean is NaN
        },
        index=index,
    )
    out = compute_ticker_metrics(frame, _no_benchmarks(), None, _AS_OF)
    assert out["avg_volume_1m"] is None


def test_price_close_uses_raw_close_and_avg_volume_is_trailing_month() -> None:
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=60)
    frame = pd.DataFrame(
        {
            "adj_close": [50.0] * 60,  # adjusted differs from raw
            "close": [100.0] * 60,
            "volume": [10.0] * 40 + [20.0] * 20,
        },
        index=index,
    )
    out = compute_ticker_metrics(frame, _no_benchmarks(), None, _AS_OF)
    assert out["price_close"] == pytest.approx(100.0)
    # Trailing month = index > 2026-05-10 → the last 22 business days
    # (2026-05-11 .. 2026-06-10), all within the 20-day block of volume 20
    # except the first two — hand-check the mean instead of trusting code:
    month_rows = frame["volume"].loc[frame.index > pd.Timestamp("2026-05-10")]
    assert out["avg_volume_1m"] == pytest.approx(float(month_rows.mean()))


# ---------------------------------------------------------------------------
# compute_ticker_metrics — fundamentals NULL guards
# ---------------------------------------------------------------------------


def test_fundamentals_happy_path_values() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400), _no_benchmarks(), _fund_row(), _AS_OF
    )
    assert out["market_cap"] == pytest.approx(10.0 * 110.0)  # shares x raw close
    assert out["pe_ratio"] == pytest.approx(1100.0 / 50.0)
    assert out["roe"] == pytest.approx(50.0 / 200.0)
    assert out["de_ratio"] == pytest.approx((1000.0 - 200.0) / 200.0)
    assert out["gross_margin"] == pytest.approx(100.0 / 400.0)
    assert out["roa"] == pytest.approx(0.07)
    assert out["investment_growth"] == pytest.approx(0.03)
    assert out["profitability_gross"] == pytest.approx(0.25)
    assert out["fundamentals_period_end"] == dt.date(2026, 3, 31)


def test_negative_net_income_nulls_pe_but_not_roe() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400),
        _no_benchmarks(),
        _fund_row(net_income_ttm=-25.0),
        _AS_OF,
    )
    assert out["pe_ratio"] is None  # negative-earnings P/E is meaningless
    assert out["roe"] == pytest.approx(-25.0 / 200.0)  # negative ROE is meaningful


def test_zero_net_income_nulls_pe() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400), _no_benchmarks(), _fund_row(net_income_ttm=0.0), _AS_OF
    )
    assert out["pe_ratio"] is None


def test_nonpositive_book_equity_nulls_roe_and_de() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400), _no_benchmarks(), _fund_row(book_equity=-5.0), _AS_OF
    )
    assert out["roe"] is None
    assert out["de_ratio"] is None
    assert out["pe_ratio"] is not None  # untouched by the equity guard


def test_null_book_equity_nulls_roe_and_de_but_not_gross_margin() -> None:
    """book_equity=None → roe and de_ratio both NULL; gross_margin still computed.

    F6.3 review: fundamentals row present but book_equity missing (e.g. the
    mother DB has a partial snapshot) must not poison the other ratios.
    """
    out = compute_ticker_metrics(
        _flat_then_jump(400),
        _no_benchmarks(),
        _fund_row(book_equity=None),
        _AS_OF,
    )
    assert out["roe"] is None
    assert out["de_ratio"] is None
    assert out["gross_margin"] is not None  # revenue + gross_profit present → computed
    assert out["market_cap"] is not None  # shares + price present → computed


def test_null_shares_nulls_market_cap_and_pe() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400),
        _no_benchmarks(),
        _fund_row(shares_outstanding=None),
        _AS_OF,
    )
    assert out["market_cap"] is None
    assert out["pe_ratio"] is None


def test_nonpositive_revenue_nulls_gross_margin() -> None:
    out = compute_ticker_metrics(
        _flat_then_jump(400), _no_benchmarks(), _fund_row(revenue=0.0), _AS_OF
    )
    assert out["gross_margin"] is None


def test_missing_fundamentals_row_nulls_all_fundamentals_metrics() -> None:
    out = compute_ticker_metrics(_flat_then_jump(400), _no_benchmarks(), None, _AS_OF)
    for col in (
        "market_cap", "pe_ratio", "roe", "roa", "gross_margin",
        "de_ratio", "investment_growth", "profitability_gross",
        "fundamentals_period_end",
    ):
        assert out[col] is None, col


# ---------------------------------------------------------------------------
# chunked() helper
# ---------------------------------------------------------------------------


def test_chunked_splits_with_remainder() -> None:
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_chunked_exact_and_oversized() -> None:
    assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]
    assert list(chunked([1, 2], 10)) == [[1, 2]]


def test_chunked_empty_yields_nothing() -> None:
    assert list(chunked([], 3)) == []


def test_chunked_rejects_nonpositive_size() -> None:
    with pytest.raises(ValueError):
        list(chunked([1, 2], 0))


# ---------------------------------------------------------------------------
# group_price_rows
# ---------------------------------------------------------------------------


def test_group_price_rows_builds_per_ticker_frames() -> None:
    rows = [
        ("AAA", dt.date(2026, 6, 9), 10.0, 11.0, 100),
        ("AAA", dt.date(2026, 6, 10), 12.0, 13.0, 200),
        ("BBB", dt.date(2026, 6, 10), 5.0, 5.5, 50),
    ]
    frames = group_price_rows(rows)
    assert set(frames) == {"AAA", "BBB"}
    aaa = frames["AAA"]
    assert list(aaa.columns) == ["adj_close", "close", "volume"]
    assert isinstance(aaa.index, pd.DatetimeIndex)
    assert aaa["adj_close"].tolist() == [10.0, 12.0]
    assert aaa["close"].tolist() == [11.0, 13.0]
    assert frames["BBB"]["volume"].tolist() == [50]


# ---------------------------------------------------------------------------
# Upsert statement
# ---------------------------------------------------------------------------


def _metrics_record(ticker: str = "AAPL") -> dict[str, Any]:
    record: dict[str, Any] = {
        "ticker": ticker,
        "computed_at": _NOW,
        "as_of": _AS_OF,
    }
    record.update(dict.fromkeys(METRIC_COLUMNS, 1.0))
    record["fundamentals_period_end"] = dt.date(2026, 3, 31)
    return record


def test_metrics_upsert_is_on_conflict_do_update_all_columns() -> None:
    sql = str(
        build_metrics_upsert([_metrics_record()]).compile(dialect=postgresql.dialect())
    )
    assert "INSERT INTO screener_metrics" in sql
    assert "ON CONFLICT (ticker) DO UPDATE" in sql
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    assert "computed_at = excluded.computed_at" in set_clause
    assert "as_of = excluded.as_of" in set_clause
    for col in METRIC_COLUMNS:
        assert f"{col} = excluded.{col}" in set_clause, col


def test_metrics_upsert_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_metrics_upsert([])


# ---------------------------------------------------------------------------
# run_metrics — batching loop shape (fake session, no DB)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "_FakeResult":
        return self

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


def _bday_rows(ticker: str, periods: int) -> list[tuple[str, dt.date, float, float, int]]:
    index = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=periods)
    return [
        (ticker, ts.date(), 100.0 + i, 100.0 + i, 1000)
        for i, ts in enumerate(index)
    ]


class FakeSession:
    """AsyncSession stand-in: dispatches execute() on the compiled statement."""

    def __init__(
        self,
        active_tickers: list[str],
        prices: dict[str, list[tuple[str, dt.date, float, float, int]]],
        fundamentals: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._active = active_tickers
        self._prices = prices
        self._fundamentals = fundamentals or {}
        self.eod_select_tickers: list[list[str]] = []
        self.fundamentals_selects = 0
        self.upserts: list[Any] = []
        self.snapshot_refreshes = 0
        self.commits = 0

    @staticmethod
    def _sql(stmt: Any) -> str:
        return str(stmt.compile(dialect=postgresql.dialect()))

    @staticmethod
    def _stmt_tickers(stmt: Any) -> list[str]:
        """Extract the in_() ticker list from a compiled statement's params."""
        for value in stmt.compile(dialect=postgresql.dialect()).params.values():
            if isinstance(value, (list, tuple)) and value and all(
                isinstance(v, str) for v in value
            ):
                return list(value)
        return []

    async def execute(self, stmt: Any) -> _FakeResult:
        sql = self._sql(stmt)
        if "FROM universe_constituents" in sql:
            return _FakeResult(list(self._active))
        if "FROM eod_prices" in sql:
            wanted = self._stmt_tickers(stmt)
            self.eod_select_tickers.append(wanted)
            rows: list[Any] = []
            for ticker in sorted(wanted):
                rows.extend(self._prices.get(ticker, []))
            return _FakeResult(rows)
        if "FROM fundamentals_snapshot" in sql:
            self.fundamentals_selects += 1
            wanted = self._stmt_tickers(stmt)
            return _FakeResult(
                [self._fundamentals[t] for t in wanted if t in self._fundamentals]
            )
        if "INSERT INTO screener_metrics" in sql:
            self.upserts.append(stmt)
            return _FakeResult([])
        if "REFRESH MATERIALIZED VIEW screener_equity_snapshot_mv" in sql:
            self.snapshot_refreshes += 1
            return _FakeResult([])
        raise AssertionError(f"Unexpected statement: {sql[:120]}")

    async def get(self, model: Any, ticker: str) -> Any:
        # Benchmarks are always fresh in these tests → no Tiingo client calls.
        return SimpleNamespace(ticker=ticker, eod_last_fetched_at=dt.datetime.now(dt.UTC))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:  # pragma: no cover - not exercised
        raise AssertionError("rollback should not happen in these tests")


def _benchmark_prices() -> dict[str, list[tuple[str, dt.date, float, float, int]]]:
    return {ticker: _bday_rows(ticker, 300) for ticker in BENCHMARK_TICKERS}


async def test_run_metrics_batches_eod_selects_and_upserts() -> None:
    prices = _benchmark_prices()
    for ticker in ("AAA", "BBB", "CCC", "EEE"):
        prices[ticker] = _bday_rows(ticker, 50)
    # DDD is active but has no EOD rows at all → skipped, not an error.
    session = FakeSession(["AAA", "BBB", "CCC", "DDD", "EEE"], prices)

    report = await run_metrics(
        session,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]  # benchmarks are fresh — never used
        batch_size=2,
        staleness_hours=24.0,
    )

    # SELECT shape: 1 benchmark load + ceil(5/2) = 3 ticker batches.
    assert session.eod_select_tickers[0] == list(BENCHMARK_TICKERS)
    assert session.eod_select_tickers[1:] == [["AAA", "BBB"], ["CCC", "DDD"], ["EEE"]]
    assert session.fundamentals_selects == 3
    # Every non-empty batch produced one upsert/commit; the MV refresh commits once.
    assert len(session.upserts) == 3
    assert session.snapshot_refreshes == 1
    assert session.commits == 4

    assert report.total_active == 5
    assert report.computed == 4
    assert report.skipped_no_eod == 1
    # 50 bdays of history: ret_1y is NULL for all 4 computed tickers.
    assert report.null_counts["ret_1y"] == 4
    assert report.null_counts["ret_1w"] == 0


async def test_run_metrics_reports_requested_tickers_outside_universe() -> None:
    prices = _benchmark_prices()
    prices["AAA"] = _bday_rows("AAA", 50)
    session = FakeSession(["AAA"], prices)

    report = await run_metrics(
        session,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
        tickers=["aaa", " ZZZ "],
        staleness_hours=24.0,
    )
    assert report.requested_not_in_universe == ["ZZZ"]
    assert report.computed == 1


async def test_run_metrics_chunks_large_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the upsert chunk forced to 2, a 5-record batch issues 3 INSERTs."""
    monkeypatch.setattr(metrics_mod, "_METRICS_UPSERT_CHUNK", 2)
    prices = _benchmark_prices()
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    for ticker in tickers:
        prices[ticker] = _bday_rows(ticker, 50)
    session = FakeSession(tickers, prices)

    report = await run_metrics(
        session,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
        batch_size=100,  # single ticker batch
        staleness_hours=24.0,
    )
    assert report.computed == 5
    assert len(session.upserts) == 3  # ceil(5/2)
    assert session.snapshot_refreshes == 1
    assert session.commits == 2  # one ticker-batch commit + one MV-refresh commit
