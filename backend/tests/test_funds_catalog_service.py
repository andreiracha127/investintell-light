"""Unit tests for the pure parts of app/services/funds_catalog.py:
sort whitelist, filter predicates, the list SELECT, NAV decimation and the
CSV projection (header + stable cells via the screener renderer).
"""

import datetime as dt

import pytest

from app.services import funds_catalog as catalog
from app.services.screener import render_csv

# ---------------------------------------------------------------------------
# Sort whitelist
# ---------------------------------------------------------------------------


def test_sort_whitelist_contains_fund_and_risk_columns() -> None:
    assert "aum_usd" in catalog.SORT_WHITELIST
    assert "expense_ratio" in catalog.SORT_WHITELIST
    assert "sharpe_1y" in catalog.SORT_WHITELIST
    assert "cvar_95_12m" in catalog.SORT_WHITELIST
    assert "peer_sharpe_pctl" in catalog.SORT_WHITELIST
    # Join keys / non-columns are NOT sortable.
    assert "instrument_id" not in catalog.SORT_WHITELIST


@pytest.mark.parametrize(
    "code",
    ["", "aum_usd; DROP TABLE funds;--", "synced_at_x", "nav"],
)
def test_sort_column_outside_whitelist_raises(code: str) -> None:
    with pytest.raises(catalog.UnknownSortColumnError):
        catalog.sort_column(code)


def test_default_sort_is_whitelisted() -> None:
    assert catalog.DEFAULT_SORT in catalog.SORT_WHITELIST


# ---------------------------------------------------------------------------
# Filter predicates
# ---------------------------------------------------------------------------


def test_no_filters_yields_only_unclassified_exclusion() -> None:
    """Baseline: with no active filters the ONLY predicate is the
    unconditional 'Unclassified' exclusion (never listed; profiles stay
    reachable by direct id)."""
    conditions = catalog.filter_conditions(catalog.FundFilters())
    assert len(conditions) == 1
    sql = str(conditions[0].compile(compile_kwargs={"literal_binds": True}))
    assert "Unclassified" in sql


def test_every_filter_contributes_one_condition() -> None:
    filters = catalog.FundFilters(
        search="vanguard",
        fund_type="etf",
        strategy_label="Large Cap",
        asset_class="equity",
        expense_ratio_max=0.005,
        aum_min=1e8,
        sharpe_1y_min=1.0,
        volatility_1y_max=0.2,
        return_1y_min=0.05,
        max_drawdown_1y_min=-0.2,
    )
    conditions = catalog.filter_conditions(filters)
    # +1: the unconditional Unclassified exclusion precedes the 10 filters.
    assert len(conditions) - 1 == len(catalog.FILTER_FIELD_NAMES) == 10


def test_search_wildcards_are_escaped() -> None:
    # conditions[0] is the Unclassified exclusion; the search predicate follows.
    conditions = catalog.filter_conditions(catalog.FundFilters(search="100%_a"))
    sql = str(
        conditions[1].compile(compile_kwargs={"literal_binds": True})
    )
    assert "100\\%\\_a" in sql


def test_build_funds_select_compiles_with_filters_and_sort() -> None:
    stmt = catalog.build_funds_select(
        catalog.FundFilters(fund_type="etf", sharpe_1y_min=0.5),
        sort="sharpe_1y",
        direction="desc",
        limit=50,
        offset=100,
    )
    sql = str(stmt)
    assert "LEFT OUTER JOIN fund_risk_latest_mv" in sql
    assert "ORDER BY fund_risk_latest_mv.sharpe_1y DESC NULLS LAST" in sql
    assert "LIMIT" in sql and "OFFSET" in sql


def test_build_funds_select_rejects_non_whitelisted_sort() -> None:
    with pytest.raises(catalog.UnknownSortColumnError):
        catalog.build_funds_select(
            catalog.FundFilters(), sort="evil", direction="asc", limit=1, offset=0
        )


# ---------------------------------------------------------------------------
# NAV decimation
# ---------------------------------------------------------------------------


def _series(n: int) -> list[tuple[dt.date, float | None]]:
    start = dt.date(2024, 1, 1)
    return [(start + dt.timedelta(days=i), float(i)) for i in range(n)]


def test_decimate_short_series_unchanged() -> None:
    points = _series(100)
    assert catalog.decimate_nav(points, target=260) == points


def test_decimate_exact_target_unchanged() -> None:
    points = _series(260)
    assert catalog.decimate_nav(points, target=260) == points


def test_decimate_long_series_keeps_endpoints_and_order() -> None:
    points = _series(2350)  # ~2y of a multi-class daily series
    out = catalog.decimate_nav(points, target=260)
    assert len(out) <= 260
    assert len(out) >= 250  # ~target, not wildly under
    assert out[0] == points[0]
    assert out[-1] == points[-1]
    dates = [d for d, _v in out]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)


def test_decimate_target_must_be_at_least_two() -> None:
    with pytest.raises(ValueError):
        catalog.decimate_nav(_series(10), target=1)


# ---------------------------------------------------------------------------
# CSV projection
# ---------------------------------------------------------------------------


def test_csv_header_and_rows() -> None:
    rows = catalog.csv_rows(
        [
            {
                "ticker": "VTI",
                "name": "Vanguard Total Stock Market ETF",
                "fund_type": "etf",
                "strategy_label": "Large Cap Blend",
                "asset_class": "equity",
                "aum_usd": 350_000_000_000,
                "expense_ratio": 0.0003,
                "return_1y": 0.1234,
                "volatility_1y": None,
                "sharpe_1y": 1.5,
                "max_drawdown_1y": -0.1,
                "peer_sharpe_pctl": 0.92,
                "elite_flag": True,
            }
        ]
    )
    body = render_csv(catalog.CSV_COLUMNS, rows)
    lines = body.splitlines()
    assert lines[0] == (
        "ticker,name,fund_type,strategy_label,asset_class,aum_usd,"
        "expense_ratio,return_1y,volatility_1y,sharpe_1y,max_drawdown_1y,"
        "peer_sharpe_pctl,elite_flag"
    )
    # Stable numeric formatting: currency 2dp, percent 6dp, None -> empty.
    assert lines[1] == (
        "VTI,Vanguard Total Stock Market ETF,etf,Large Cap Blend,equity,"
        "350000000000.00,0.000300,0.123400,,1.500000,-0.100000,0.920000,true"
    )


def test_csv_elite_flag_false_and_none() -> None:
    base = dict.fromkeys(code for code, _h, _t in catalog.CSV_COLUMNS)
    rows = catalog.csv_rows([{**base, "elite_flag": False}, dict(base)])
    assert rows[0]["elite_flag"] == "false"
    assert rows[1]["elite_flag"] is None
