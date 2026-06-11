"""Integrity tests for the screener metric catalog (app/screener/catalog.py).

The catalog is THE column whitelist for every dynamic screener query, so its
invariants are load-bearing: every code must be a real screener_metrics
column, codes must be unique (the Tiingo study found their live catalog
shipped metricCode ``percentAboveBelowSMA20`` twice — duplicates silently
break code→definition lookups), and preset bands must be sane.
"""

from app.screener.catalog import CATALOG, CATALOG_BY_CODE, get_metric
from app.sync.metrics import METRIC_COLUMNS

_VALID_DATA_TYPES = {"percent", "float", "currency", "int"}


def test_every_code_is_a_metric_column() -> None:
    for metric in CATALOG:
        assert metric.code in METRIC_COLUMNS, metric.code


def test_catalog_covers_all_screenable_metric_columns() -> None:
    """Exactly METRIC_COLUMNS minus fundamentals_period_end (provenance, not
    a screenable quantity) — keeps catalog, model and metrics job in lockstep."""
    expected = set(METRIC_COLUMNS) - {"fundamentals_period_end"}
    assert {metric.code for metric in CATALOG} == expected


def test_no_duplicate_codes() -> None:
    """The Tiingo-bug lesson: duplicated metricCode percentAboveBelowSMA20."""
    codes = [metric.code for metric in CATALOG]
    assert len(codes) == len(set(codes))


def test_lookup_helpers_agree_with_the_catalog() -> None:
    assert len(CATALOG_BY_CODE) == len(CATALOG)
    assert get_metric("pe_ratio") is CATALOG_BY_CODE["pe_ratio"]
    assert get_metric("not_a_metric") is None
    assert get_metric("fundamentals_period_end") is None


def test_data_types_are_valid() -> None:
    for metric in CATALOG:
        assert metric.data_type in _VALID_DATA_TYPES, metric.code


def test_descriptive_fields_are_populated() -> None:
    for metric in CATALOG:
        assert metric.name, metric.code
        assert metric.abbreviation, metric.code
        assert metric.category, metric.code
        assert metric.sub_category, metric.code
        assert metric.scale_note, metric.code


def test_presets_are_sane() -> None:
    """Bounded presets must have min <= max; names unique within a metric."""
    for metric in CATALOG:
        assert metric.presets, metric.code
        names = [preset.name for preset in metric.presets]
        assert len(names) == len(set(names)), metric.code
        for preset in metric.presets:
            if preset.min_value is not None and preset.max_value is not None:
                assert preset.min_value <= preset.max_value, (metric.code, preset.name)


def test_every_metric_has_a_custom_preset_with_null_bounds() -> None:
    for metric in CATALOG:
        custom = [preset for preset in metric.presets if preset.name == "Custom"]
        assert len(custom) == 1, metric.code
        assert custom[0].min_value is None
        assert custom[0].max_value is None
