"""Unit tests for app/services/screener.py — the pure helpers.

Histogram, CSV rendering and the dynamic-but-whitelisted SQL builders are
tested directly (the SQL builders by compiling to PostgreSQL text with
literal binds — deterministic, no live DB). Route-level behavior lives in
test_screener_routes.py.
"""

import math
from types import SimpleNamespace

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from app.services import screener as svc


def _filter(
    metric_code: str = "pe_ratio",
    min_value: float | None = None,
    max_value: float | None = None,
    position: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        metric_code=metric_code, min_value=min_value, max_value=max_value, position=position
    )


def _compile(stmt: Select) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# ---------------------------------------------------------------------------
# build_histogram
# ---------------------------------------------------------------------------


def test_histogram_linear_edges_and_normalization() -> None:
    values = [float(v) for v in range(0, 101)]  # 0..100
    dist = svc.build_histogram(values, "percent")

    assert len(dist.bin_edges) == svc.HISTOGRAM_BINS + 1
    assert len(dist.counts) == svc.HISTOGRAM_BINS
    assert len(dist.counts_normalized) == svc.HISTOGRAM_BINS
    assert dist.bin_edges[0] == 0.0
    assert dist.bin_edges[-1] == 100.0
    # Linear: constant step between consecutive edges.
    steps = [b - a for a, b in zip(dist.bin_edges, dist.bin_edges[1:], strict=False)]
    assert all(math.isclose(step, steps[0]) for step in steps)
    # Every value lands in a bin; normalization peaks at exactly 1.0 in 0..1.
    assert sum(dist.counts) == len(values)
    assert max(dist.counts_normalized) == 1.0
    assert all(0.0 <= x <= 1.0 for x in dist.counts_normalized)


def test_histogram_log_spaced_for_positive_currency() -> None:
    """The study's market-cap pattern: equal-RATIO bins across magnitudes."""
    market_caps = [10.0**exp for exp in range(6, 13)]  # $1M .. $1T
    dist = svc.build_histogram(market_caps, "currency")

    ratios = [b / a for a, b in zip(dist.bin_edges, dist.bin_edges[1:], strict=False)]
    assert all(math.isclose(r, ratios[0], rel_tol=1e-9) for r in ratios)
    assert math.isclose(dist.bin_edges[0], 1e6)
    assert math.isclose(dist.bin_edges[-1], 1e12)
    assert sum(dist.counts) == len(market_caps)  # min AND max are both counted


def test_histogram_log_spaced_for_positive_int() -> None:
    """F6.4 review: avg_volume_1m has data_type='int' and spans many magnitudes.

    Volume values like 1K–10M need log-spacing just like market_cap; the log
    branch must fire when data_type='int' and all values > 0.
    """
    volumes = [10.0**exp for exp in range(3, 8)]  # 1 000 .. 10 000 000
    dist = svc.build_histogram(volumes, "int")

    # Equal-ratio bins (log-spaced).
    ratios = [b / a for a, b in zip(dist.bin_edges, dist.bin_edges[1:], strict=False)]
    assert all(math.isclose(r, ratios[0], rel_tol=1e-9) for r in ratios)
    assert sum(dist.counts) == len(volumes)


def test_histogram_currency_with_nonpositive_value_falls_back_to_linear() -> None:
    dist = svc.build_histogram([0.0, 10.0, 100.0], "currency")
    steps = [b - a for a, b in zip(dist.bin_edges, dist.bin_edges[1:], strict=False)]
    assert all(math.isclose(step, steps[0]) for step in steps)
    assert sum(dist.counts) == 3


def test_histogram_single_distinct_value_widens_instead_of_crashing() -> None:
    dist = svc.build_histogram([7.0, 7.0, 7.0], "float")
    assert sum(dist.counts) == 3
    assert dist.bin_edges[0] < 7.0 < dist.bin_edges[-1]


def test_histogram_empty_fails_loud_with_actionable_message() -> None:
    with pytest.raises(svc.MetricDataUnavailableError, match="compute_screener_metrics"):
        svc.build_histogram([], "float")


# ---------------------------------------------------------------------------
# Whitelisting + filter predicates
# ---------------------------------------------------------------------------


def test_metric_column_rejects_codes_outside_the_catalog() -> None:
    with pytest.raises(svc.UnknownMetricCodeError):
        svc.metric_column("computed_at")  # a real column, but NOT screenable
    with pytest.raises(svc.UnknownMetricCodeError):
        svc.metric_column("pe_ratio; DROP TABLE screener_metrics;--")


def test_filter_conditions_exclude_nulls_and_apply_both_bounds() -> None:
    filters = [
        _filter("pe_ratio", 10.0, 15.0, position=0),
        _filter("market_cap", 2e9, None, position=1),
        _filter("ret_1y", None, None, position=2),  # selected, unbounded
    ]
    sql = _compile(
        svc.build_count_select(filters, search=None)
    )
    # NULL exclusion for EVERY filter — including the unbounded one.
    assert sql.count("IS NOT NULL") == 3
    assert "screener_equity_snapshot_mv.pe_ratio >= 10.0" in sql
    assert "screener_equity_snapshot_mv.pe_ratio <= 15.0" in sql
    assert "screener_equity_snapshot_mv.market_cap >= 2000000000.0" in sql
    # The unbounded filter contributes no range predicates.
    assert "ret_1y >=" not in sql
    assert "ret_1y <=" not in sql
    # Active-universe scope.
    assert "screener_equity_snapshot_mv.status = 'active'" in sql


def test_filter_conditions_reject_unknown_codes() -> None:
    with pytest.raises(svc.UnknownMetricCodeError):
        svc.filter_conditions([_filter("fundamentals_period_end")])


# ---------------------------------------------------------------------------
# Results SELECT builder
# ---------------------------------------------------------------------------


def test_results_select_orders_pages_and_escapes_search() -> None:
    filters = [_filter("pe_ratio", 10.0, 15.0)]
    sql = _compile(
        svc.build_results_select(
            filters,
            sort="pe_ratio",
            direction="desc",
            search="A%_\\B",
            limit=25,
            offset=50,
        )
    )
    assert "ORDER BY screener_equity_snapshot_mv.pe_ratio DESC NULLS LAST" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql
    # Prefix match on BOTH ticker and name, with an explicit escape char.
    assert sql.count(" LIKE ") == 2
    assert "lower(screener_equity_snapshot_mv.ticker)" in sql
    assert "lower(screener_equity_snapshot_mv.name)" in sql
    assert sql.count("ESCAPE") == 2


def test_escape_like_neutralizes_user_wildcards() -> None:
    """Only the trailing % appended by the service is a live wildcard."""
    assert svc._escape_like("A%_\\B") == "A\\%\\_\\\\B"
    assert svc._escape_like("plain") == "plain"


def test_results_select_rejects_sort_outside_the_screen_columns() -> None:
    with pytest.raises(svc.UnknownMetricCodeError):
        svc.build_results_select(
            [_filter("pe_ratio")],
            sort="market_cap",  # a catalog metric, but NOT selected by this screen
            direction="asc",
            search=None,
            limit=25,
            offset=0,
        )


def test_result_columns_position_order_and_base_columns() -> None:
    filters = [
        _filter("market_cap", position=1),
        _filter("pe_ratio", position=0),
    ]
    columns = svc.result_columns(filters)
    assert [code for code, _n, _d in columns] == ["ticker", "name", "pe_ratio", "market_cap"]
    assert columns[0][2] == "string"
    assert columns[2][2] == "float"
    assert columns[3][2] == "currency"


def test_result_columns_fail_loud_on_unknown_persisted_code() -> None:
    with pytest.raises(svc.UnknownMetricCodeError):
        svc.result_columns([_filter("no_such_metric")])


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


def test_render_csv_shape_and_null_cells() -> None:
    columns = [
        ("ticker", "Ticker", "string"),
        ("name", "Name", "string"),
        ("pe_ratio", "Price / Earnings (TTM)", "float"),
    ]
    rows = [
        {"ticker": "AAPL", "name": "Apple, Inc.", "pe_ratio": 28.5},
        {"ticker": "MSFT", "name": "Microsoft Corp", "pe_ratio": None},
    ]
    body = svc.render_csv(columns, rows)
    lines = body.strip().split("\n")
    assert lines[0] == "ticker,name,pe_ratio"
    assert lines[1] == 'AAPL,"Apple, Inc.",28.500000'
    assert lines[2] == "MSFT,Microsoft Corp,"


def test_render_csv_no_scientific_notation() -> None:
    """F6.4 review: CSV cells must never contain 'e'/'E' (scientific notation).

    market_cap 2.5e12 → '2500000000000.00' (currency, 2 d.p.)
    avg_volume_1m 1234567 → '1234567' (int, 0 d.p.)
    roe 1e-05 → '0.000010' (percent, 6 d.p.)
    """
    columns = [
        ("ticker", "Ticker", "string"),
        ("market_cap", "Market Cap", "currency"),
        ("avg_volume_1m", "Avg Volume 1M", "int"),
        ("roe", "Return on Equity", "percent"),
    ]
    rows = [
        {
            "ticker": "BIG",
            "market_cap": 2.5e12,
            "avg_volume_1m": 1_234_567.0,
            "roe": 1e-5,
        }
    ]
    body = svc.render_csv(columns, rows)
    lines = body.strip().split("\n")
    data_line = lines[1]

    assert "e" not in data_line.lower(), f"scientific notation found: {data_line!r}"
    assert "2500000000000.00" in data_line
    assert "1234567" in data_line
    assert "0.000010" in data_line


# ---------------------------------------------------------------------------
# compile-level: metric-values SELECT covers active snapshot + IS NOT NULL
# ---------------------------------------------------------------------------


def test_select_metric_values_query_filters_active_snapshot_and_not_null() -> None:
    """F6.4 review: the build/distribution feed SELECT must restrict to the
    active snapshot (status = 'active') and exclude NULL values for the metric.

    Compiled against the PostgreSQL dialect with literal binds — deterministic,
    no live DB required.
    """
    from sqlalchemy.dialects import postgresql  # noqa: PLC0415

    col = svc.metric_column("pe_ratio")
    stmt = svc._active_universe_select(col).where(col.is_not(None))
    sql = str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "screener_equity_snapshot_mv.status = 'active'" in sql
    assert "screener_equity_snapshot_mv.pe_ratio IS NOT NULL" in sql
