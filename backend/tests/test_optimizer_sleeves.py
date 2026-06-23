"""COMBO S4b.1 — the 7-sleeve / category-proxy model (fund -> strategy_label ->
proxy -> sleeve). Pure data/mapping layer; no DB, no solve. Ported from the
calibrated harness and validated against the production catalog
(funds_v.strategy_label)."""

from app.optimizer import sleeves
from app.services import taa_bands as tb


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


def test_hedge_label_is_not_a_base_sleeve() -> None:
    """Inverse/Hedge maps to 'hedge' (SH research-only) — distinct from the 7
    base sleeves so the two-level can exclude it."""
    assert sleeves.fund_sleeve_group("Inverse / Hedge", None) == "hedge"
    assert "hedge" not in sleeves.SLEEVE_GROUPS


def test_sleeve_groups_match_production_taa_bands() -> None:
    """The 7 base sleeves are exactly taa_bands.SLEEVE_GROUPS (single source of
    truth for the per-profile bands)."""
    assert sleeves.SLEEVE_GROUPS == tb.SLEEVE_GROUPS


def test_group_benchmark_covers_every_sleeve() -> None:
    """One canonical proxy per sleeve, each a known proxy in PROXY_TO_GROUP, each
    mapping back to its own sleeve."""
    assert set(sleeves.GROUP_BENCHMARK) == set(sleeves.SLEEVE_GROUPS)
    for g, proxy in sleeves.GROUP_BENCHMARK.items():
        assert sleeves.PROXY_TO_GROUP[proxy] == g


def test_proxy_fill_is_authorized_only_for_gold_and_long_short() -> None:
    """gold (never a fund) and long_short (few funds) get an authorized fill;
    each fill proxy belongs to its sleeve."""
    assert set(sleeves.GROUP_PROXY_FILL) == {"gold", "long_short"}
    for g, fills in sleeves.GROUP_PROXY_FILL.items():
        for px in fills:
            assert sleeves.PROXY_TO_GROUP[px] == g


def test_label_to_group_consistency() -> None:
    """Every label's proxy has a known group; derived LABEL_TO_GROUP agrees."""
    for label, proxy in sleeves.LABEL_TO_PROXY.items():
        assert proxy in sleeves.PROXY_TO_GROUP
        assert sleeves.LABEL_TO_GROUP[label] == sleeves.PROXY_TO_GROUP[proxy]
