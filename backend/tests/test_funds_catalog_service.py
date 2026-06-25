"""Unit tests for the pure parts of app/services/funds_catalog.py:
sort whitelist, filter predicates, the list SELECT, NAV decimation and the
CSV projection (header + stable cells via the screener renderer).
"""

import datetime as dt
import inspect
import uuid

import pytest

from app.services import funds_catalog as catalog
from app.services.funds_catalog import build_nav_series_select
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


def test_list_sort_whitelist_includes_manager_name() -> None:
    # The Manager column is a correlated subquery resolved per query — it is
    # sortable on the materialized list path even though it is NOT a column of
    # fund_risk_latest (so it is absent from the non-materialized whitelist).
    assert "manager_name" in catalog.LIST_SORT_WHITELIST
    assert "manager_name" not in catalog.SORT_WHITELIST


def test_list_sort_whitelist_agrees_with_build_funds_select() -> None:
    # Regression guard: the route's validation gate and the SQL builder MUST
    # accept exactly the same sort codes. A drift here is precisely the bug
    # that 422-ed the Manager column (gate said no, builder said yes).
    for code in catalog.LIST_SORT_WHITELIST:
        catalog.build_funds_select(
            catalog.FundFilters(), sort=code, direction="asc", limit=1, offset=0
        )


def test_list_sort_whitelist_excludes_columns_absent_from_the_mv() -> None:
    # Tier-3 EVT/GARCH metrics exist on fund_risk_latest (and so on the
    # non-materialized whitelist) but are not materialized in funds_list_mv,
    # so the list path cannot sort by them.
    for code in ("evt_xi_shape", "cvar_999_evt", "volatility_garch"):
        assert code in catalog.SORT_WHITELIST
        assert code not in catalog.LIST_SORT_WHITELIST
        with pytest.raises(catalog.UnknownSortColumnError):
            catalog.build_funds_select(
                catalog.FundFilters(), sort=code, direction="asc", limit=1, offset=0
            )


# ---------------------------------------------------------------------------
# Filter predicates
# ---------------------------------------------------------------------------


def test_no_filters_yields_catalog_quality_gates() -> None:
    """Baseline: catalog universes always require classified funds with AUM.

    Direct profile pages stay reachable by id; list/candidate universes suppress
    rows whose missing Assets can make upstream risk returns explode.
    """
    conditions = catalog.filter_conditions(catalog.FundFilters())
    assert len(conditions) == 2
    sql = " ".join(
        str(condition.compile(compile_kwargs={"literal_binds": True}))
        for condition in conditions
    )
    assert "Unclassified" in sql
    assert "funds_profile_mv.aum_usd IS NOT NULL" in sql


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
    # +2: unconditional Unclassified + missing-AUM exclusions precede filters.
    assert len(conditions) - 2 == len(catalog.FILTER_FIELD_NAMES) == 10


def test_search_wildcards_are_escaped() -> None:
    # conditions[0:2] are the fixed catalog gates; search follows.
    conditions = catalog.filter_conditions(catalog.FundFilters(search="100%_a"))
    sql = str(
        conditions[2].compile(compile_kwargs={"literal_binds": True})
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
    assert "funds_list_mv" in sql
    assert "funds_list_mv.aum_usd IS NOT NULL" in sql
    assert "ORDER BY funds_list_mv.sharpe_1y DESC NULLS LAST" in sql
    assert "LIMIT" in sql and "OFFSET" in sql


def test_return_1y_projection_and_sort_suppress_glitch_values() -> None:
    stmt = catalog.build_funds_select(
        catalog.FundFilters(return_1y_min=0.0),
        sort="return_1y",
        direction="desc",
        limit=20,
        offset=0,
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "CASE WHEN" in sql
    assert "abs(funds_list_mv.return_1y) > 10.0" in sql
    assert "AS return_1y" in sql
    assert "ORDER BY return_1y DESC NULLS LAST" in sql


def test_fund_profile_uses_materialized_benchmark_snapshot() -> None:
    source = inspect.getsource(catalog.fetch_fund_profile)
    assert "funds_profile_mv" in source
    assert "fund_top_holdings_mv" in source
    assert "fund_classes_latest_mv" in source
    assert "fund_benchmark_candidates_mv" in source
    assert "fund_benchmark_candidates_v" not in source
    assert "funds_v" not in source
    assert "fund_holdings_v" not in source
    assert "fund_classes_v" not in source


def test_build_funds_select_rejects_non_whitelisted_sort() -> None:
    with pytest.raises(catalog.UnknownSortColumnError):
        catalog.build_funds_select(
            catalog.FundFilters(), sort="evil", direction="asc", limit=1, offset=0
        )


def test_manager_name_resolves_investment_adviser_not_registrant() -> None:
    # The Manager column must resolve the INVESTMENT ADVISER via the N-CEN
    # crosswalk (sec_fund_adviser) + Form ADV firm name (sec_managers), keyed
    # by series_id — NOT the registrant/trust via the old instrument_identity
    # CIK subquery (that was the bug: it surfaced the trust, e.g. "iSHARES
    # TRUST" instead of "BLACKROCK FUND ADVISORS").
    sql = str(
        catalog.build_funds_select(
            catalog.FundFilters(), sort="aum_usd", direction="desc", limit=1, offset=0
        )
    )
    assert "sec_fund_adviser" in sql
    assert "instrument_identity" not in sql


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
# NAV series SELECT (raw nav_timeseries hypertable — Task 2.4)
# ---------------------------------------------------------------------------


def test_nav_series_select_targets_nav_timeseries() -> None:
    stmt = build_nav_series_select(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        dt.date(2024, 1, 1),
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "nav_timeseries" in sql
    assert "nav_date" in sql


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
                "manager_score": 88.5,
                "elite_flag": True,
            }
        ]
    )
    body = render_csv(catalog.CSV_COLUMNS, rows)
    lines = body.splitlines()
    assert lines[0] == (
        "ticker,name,fund_type,strategy_label,asset_class,aum_usd,"
        "expense_ratio,return_1y,volatility_1y,sharpe_1y,max_drawdown_1y,"
        "peer_sharpe_pctl,manager_score,elite_flag"
    )
    # Stable numeric formatting: currency 2dp, percent 6dp, None -> empty.
    assert lines[1] == (
        "VTI,Vanguard Total Stock Market ETF,etf,Large Cap Blend,equity,"
        "350000000000.00,0.000300,0.123400,,1.500000,-0.100000,0.920000,88.500000,true"
    )


def test_csv_elite_flag_false_and_none() -> None:
    base = dict.fromkeys(code for code, _h, _t in catalog.CSV_COLUMNS)
    rows = catalog.csv_rows([{**base, "elite_flag": False}, dict(base)])
    assert rows[0]["elite_flag"] == "false"
    assert rows[1]["elite_flag"] is None
