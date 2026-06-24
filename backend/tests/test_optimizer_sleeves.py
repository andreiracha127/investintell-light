"""COMBO S4b.1 — the 7-sleeve / category-proxy model (fund -> strategy_label ->
proxy -> sleeve). Pure data/mapping layer; no DB, no solve. Ported from the
calibrated harness and validated against the production catalog
(funds_v.strategy_label)."""

from app.optimizer import sleeves
from app.services import quadrant_policy as qp


def test_label_maps_to_finest_sleeve() -> None:
    """A known strategy_label resolves through LABEL_TO_PROXY -> PROXY_TO_GROUP."""
    assert sleeves.fund_sleeve_group("Large Blend", None) == "equity"
    assert sleeves.fund_sleeve_group("Large Growth", None) == "equity"
    assert sleeves.fund_sleeve_group("Government Bond", None) == "fixed_income"
    assert sleeves.fund_sleeve_group("Technology", None) == "thematic"
    assert sleeves.fund_sleeve_group("Energy Equity", None) == "thematic"
    assert sleeves.fund_sleeve_group("Real Estate", None) == "alternatives"
    assert sleeves.fund_sleeve_group("Long/Short Equity", None) == "long_short"
    assert sleeves.fund_sleeve_group("Cash Equivalent", None) == "cash"


def test_label_wins_over_asset_class() -> None:
    """When both are present the finer strategy_label drives the sleeve."""
    assert sleeves.fund_sleeve_group("Technology", "equity") == "thematic"


def test_falls_back_to_asset_class_4classes() -> None:
    """No usable label -> the lenient 4-class asset_class (equity/fixed_income/
    alternatives/cash) is the sleeve."""
    assert sleeves.fund_sleeve_group(None, "fixed_income") == "fixed_income"
    assert sleeves.fund_sleeve_group("Core", "alternatives") == "alternatives"
    assert sleeves.fund_sleeve_group("Balanced", "cash") == "cash"


def test_unknown_everything_defaults_to_equity() -> None:
    """Raw equities (no asset_class) and unknown labels default to equity."""
    assert sleeves.fund_sleeve_group(None, None) == "equity"
    assert sleeves.fund_sleeve_group("Unclassified", None) == "equity"
    assert sleeves.fund_sleeve_group(None, "multi_asset") == "equity"


def test_hedge_label_not_in_proxy_map() -> None:
    """SH/hedge are NOT structural sleeves (freeze §13: the 7 structural sleeves are
    cash/equity/fixed_income/thematic/alternatives/gold/long_short). The Inverse/Hedge
    label and the SH proxy are retired from the sleeve map (research-only)."""
    assert "Inverse / Hedge" not in sleeves.LABEL_TO_PROXY
    assert "SH" not in sleeves.PROXY_TO_GROUP
    assert "hedge" not in sleeves.SLEEVE_GROUPS


def test_inverse_fund_does_not_resolve_to_hedge() -> None:
    """An inverse/hedge labelled fund now falls through to the asset_class/equity
    default, never the removed 'hedge' sleeve."""
    sleeve = sleeves.fund_sleeve_group("Inverse / Hedge", None)
    assert sleeve != "hedge"


def test_sleeve_groups_match_quadrant_policy() -> None:
    """The 7 base sleeves are exactly quadrant_policy.STRUCTURAL_SLEEVES (the single
    source of truth for the per-profile bands; taa_bands.SLEEVE_GROUPS retired)."""
    assert sleeves.SLEEVE_GROUPS == list(qp.STRUCTURAL_SLEEVES)


def test_group_benchmark_covers_every_sleeve() -> None:
    """One canonical proxy per sleeve, each a known proxy in PROXY_TO_GROUP, each
    mapping back to its own sleeve."""
    assert set(sleeves.GROUP_BENCHMARK) == set(sleeves.SLEEVE_GROUPS)
    for g, proxy in sleeves.GROUP_BENCHMARK.items():
        assert sleeves.PROXY_TO_GROUP[proxy] == g


def test_proxy_fill_is_authorized_for_every_policy_sleeve() -> None:
    """complete_macro may fill any missing policy sleeve with its authorized proxy;
    each fill proxy belongs to its sleeve."""
    assert set(sleeves.GROUP_PROXY_FILL) == set(sleeves.SLEEVE_GROUPS)
    for g, fills in sleeves.GROUP_PROXY_FILL.items():
        for px in fills:
            assert sleeves.PROXY_TO_GROUP[px] == g


def test_fixed_income_proxy_fills_cover_product_categories() -> None:
    assert sleeves.GROUP_PROXY_FILL["fixed_income"] == [
        "GOVT", "LQD", "HYG", "TIP", "BND"
    ]


def test_canonical_category_consolidates_cash_aliases() -> None:
    cash = sleeves.category_for_fund("Cash Equivalent", None)
    gov_mm = sleeves.category_for_fund("Government Money Market", None)
    assert cash.category_id == "CASH_USD/BIL"
    assert gov_mm.category_id == cash.category_id


def test_precious_metals_maps_to_alternatives_not_gold() -> None:
    spec = sleeves.category_for_fund("Precious Metals", None)
    assert spec.benchmark_ticker == "RING"
    assert spec.sleeve_id == "alternatives"
    assert sleeves.category_for_proxy("GLD").sleeve_id == "gold"


def test_label_to_group_consistency() -> None:
    """Every label's proxy has a known group; derived LABEL_TO_GROUP agrees."""
    for label, proxy in sleeves.LABEL_TO_PROXY.items():
        assert proxy in sleeves.PROXY_TO_GROUP
        assert sleeves.LABEL_TO_GROUP[label] == sleeves.PROXY_TO_GROUP[proxy]
