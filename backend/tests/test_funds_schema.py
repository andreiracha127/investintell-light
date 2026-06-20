"""Unit tests for app/schemas/funds.py — the manager-name title-casing that
turns the ALL-CAPS Form ADV adviser names into legible display strings.
"""

import uuid

import pytest

from app.schemas.funds import FundBenchmarkOut, FundListItem, format_company_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("VANGUARD GROUP INC", "Vanguard Group Inc"),
        ("BLACKROCK FUND ADVISORS", "Blackrock Fund Advisors"),
        # Legal suffix + ampersand stay upper.
        (
            "FIDELITY MANAGEMENT & RESEARCH COMPANY LLC",
            "Fidelity Management & Research Company LLC",
        ),
        # Connector 'and' stays lower (not leading).
        (
            "CAPITAL RESEARCH AND MANAGEMENT COMPANY",
            "Capital Research and Management Company",
        ),
        # Dotted initials keep their case.
        (
            "J.P. MORGAN INVESTMENT MANAGEMENT INC.",
            "J.P. Morgan Investment Management Inc.",
        ),
        # Already mixed-case (N-CEN source) — trusted, returned unchanged.
        ("T. Rowe Price Associates, Inc.", "T. Rowe Price Associates, Inc."),
        ("BlackRock Fund Advisors", "BlackRock Fund Advisors"),
        (None, None),
        ("", ""),
    ],
)
def test_format_company_name(raw: str | None, expected: str | None) -> None:
    assert format_company_name(raw) == expected


def _item(manager_name: str | None) -> FundListItem:
    return FundListItem.model_validate(
        {
            "instrument_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "series_id": "S000000001",
            "ticker": "IVV",
            "name": "iShares Core S&P 500 ETF",
            "fund_type": "etf",
            "strategy_label": "Large Blend",
            "asset_class": "equity",
            "is_index": True,
            "expense_ratio": 0.0003,
            "aum_usd": 7.6e11,
            "return_1y": 0.26,
            "volatility_1y": 0.12,
            "sharpe_1y": 1.6,
            "max_drawdown_1y": -0.08,
            "peer_sharpe_pctl": 0.9,
            "manager_score": None,
            "elite_flag": None,
            "manager_name": manager_name,
        }
    )


def test_list_item_title_cases_manager_name() -> None:
    assert _item("BLACKROCK FUND ADVISORS").manager_name == "Blackrock Fund Advisors"


def test_list_item_manager_name_none_stays_none() -> None:
    assert _item(None).manager_name is None


def test_benchmark_out_can_represent_proxy_conflict() -> None:
    out = FundBenchmarkOut(
        name="Russell 2500 Growth Index",
        proxy_ticker=None,
        proxy_instrument_id=None,
        proxy_fit_quality_score=None,
        proxy_asset_class=None,
        resolution_method="class_name_exact",
        resolution_conflict=True,
        proxy_candidates=["IJT", "SMLG"],
        canonical_name_matches=["Russell 2500 Growth", "Russell 2500 Growth Index"],
    )

    assert out.resolution_conflict is True
    assert out.proxy_ticker is None
    assert out.proxy_candidates == ["IJT", "SMLG"]
