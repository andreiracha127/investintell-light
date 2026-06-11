"""Static, backend-owned metric catalog for the screener (F6.4).

One ``MetricDef`` per screenable ``screener_metrics`` column (every
``METRIC_COLUMNS`` entry except ``fundamentals_period_end``, which is
provenance, not a screenable quantity). The catalog drives:

- ``GET /screener/metrics`` — the Select Metrics UI (categories + presets);
- column WHITELISTING for every dynamic results/build query: user-supplied
  metric codes are only ever resolved through this registry, never
  interpolated into SQL.

Preset bands follow the Tiingo screener study's shape ({name, min, max} with
null = unbounded) but with static, sensible bounds; every metric also carries
a "Custom" preset with both bounds null. Scale contract (project-wide): all
"percent" metrics are decimal fractions (0.05 = 5%), never 0-100 — the preset
bounds here are in the SAME unit as the stored column.

Uniqueness is validated at import time AND unit-tested: the study found a
real Tiingo bug where metricCode ``percentAboveBelowSMA20`` appeared twice in
their catalog — duplicate codes silently break code→definition lookups.
"""

from dataclasses import dataclass
from typing import Literal

from app.models.screener_metrics import ScreenerMetrics

DataType = Literal["percent", "float", "currency", "int"]

_FRACTION_NOTE = "Decimal fraction (0.05 = 5%), never 0-100."
_RATIO_NOTE = "Unitless ratio."
_CURRENCY_NOTE = "Currency units (USD)."


@dataclass(frozen=True)
class PresetBand:
    """One selectable filter band; a null bound means unbounded on that side."""

    name: str
    min_value: float | None
    max_value: float | None


@dataclass(frozen=True)
class MetricDef:
    """One screenable metric — code is the ``screener_metrics`` column name."""

    code: str
    name: str
    abbreviation: str
    category: str
    sub_category: str
    data_type: DataType
    scale_note: str
    presets: tuple[PresetBand, ...]


_CUSTOM = PresetBand("Custom", None, None)


def _bands(*bounds: tuple[str, float | None, float | None]) -> tuple[PresetBand, ...]:
    """Build a preset tuple from (name, min, max) triples + the Custom band."""
    # TODO(F-later): data-driven quantile preset bands
    return tuple(PresetBand(name, lo, hi) for name, lo, hi in bounds) + (_CUSTOM,)


# ---------------------------------------------------------------------------
# Preset band families (static, sensible bounds — see module docstring)
# ---------------------------------------------------------------------------

_RETURN_PRESETS = _bands(
    ("Below -10%", None, -0.10),
    ("-10% to -5%", -0.10, -0.05),
    ("-5% to 0%", -0.05, 0.0),
    ("0% to 5%", 0.0, 0.05),
    ("5% to 10%", 0.05, 0.10),
    ("Above 10%", 0.10, None),
)

# Annualized vol, quintile-ish static bands over typical US-equity levels.
_VOL_PRESETS = _bands(
    ("Below 15%", None, 0.15),
    ("15% to 25%", 0.15, 0.25),
    ("25% to 40%", 0.25, 0.40),
    ("40% to 60%", 0.40, 0.60),
    ("Above 60%", 0.60, None),
)

# Betas: bands inside -2.5..2.5 plus open tails.
_BETA_PRESETS = _bands(
    ("Below -2.5", None, -2.5),
    ("-2.5 to 0", -2.5, 0.0),
    ("0 to 0.5", 0.0, 0.5),
    ("0.5 to 1", 0.5, 1.0),
    ("1 to 1.5", 1.0, 1.5),
    ("1.5 to 2.5", 1.5, 2.5),
    ("Above 2.5", 2.5, None),
)

# Correlations: the full ±1 range in bands of 0.4.
_CORR_PRESETS = _bands(
    ("-1 to -0.6", -1.0, -0.6),
    ("-0.6 to -0.2", -0.6, -0.2),
    ("-0.2 to 0.2", -0.2, 0.2),
    ("0.2 to 0.6", 0.2, 0.6),
    ("0.6 to 1", 0.6, 1.0),
)

_PRICE_PRESETS = _bands(
    ("Below $5", None, 5.0),
    ("$5 to $20", 5.0, 20.0),
    ("$20 to $50", 20.0, 50.0),
    ("$50 to $200", 50.0, 200.0),
    ("Above $200", 200.0, None),
)

_VOLUME_PRESETS = _bands(
    ("Below 100K", None, 1e5),
    ("100K to 1M", 1e5, 1e6),
    ("1M to 10M", 1e6, 1e7),
    ("Above 10M", 1e7, None),
)

# Market cap: the conventional nano/micro/small/mid/large size buckets.
_MARKET_CAP_PRESETS = _bands(
    ("Nano (< $50M)", None, 50e6),
    ("Micro ($50M to $300M)", 50e6, 300e6),
    ("Small ($300M to $2B)", 300e6, 2e9),
    ("Mid ($2B to $10B)", 2e9, 10e9),
    ("Large (> $10B)", 10e9, None),
)

_PE_PRESETS = _bands(
    ("0 to 5", 0.0, 5.0),
    ("5 to 10", 5.0, 10.0),
    ("10 to 15", 10.0, 15.0),
    ("15 to 25", 15.0, 25.0),
    ("Above 25", 25.0, None),
)

# Margins / returns-on-capital: quartile-ish fraction bands.
_MARGIN_PRESETS = _bands(
    ("Negative", None, 0.0),
    ("0% to 10%", 0.0, 0.10),
    ("10% to 20%", 0.10, 0.20),
    ("20% to 35%", 0.20, 0.35),
    ("Above 35%", 0.35, None),
)

_DE_PRESETS = _bands(
    ("0 to 0.5", 0.0, 0.5),
    ("0.5 to 1", 0.5, 1.0),
    ("1 to 2", 1.0, 2.0),
    ("Above 2", 2.0, None),
)

_GROWTH_PRESETS = _bands(
    ("Below -20%", None, -0.20),
    ("-20% to 0%", -0.20, 0.0),
    ("0% to 20%", 0.0, 0.20),
    ("20% to 50%", 0.20, 0.50),
    ("Above 50%", 0.50, None),
)


# ---------------------------------------------------------------------------
# Catalog assembly (family loops keep code/name/abbreviation in lockstep)
# ---------------------------------------------------------------------------

_RETURN_DEFS: tuple[tuple[str, str, str], ...] = (
    ("ret_1w", "1-Week Return", "Ret 1W"),
    ("ret_1m", "1-Month Return", "Ret 1M"),
    ("ret_3m", "3-Month Return", "Ret 3M"),
    ("ret_6m", "6-Month Return", "Ret 6M"),
    ("ret_1y", "1-Year Return", "Ret 1Y"),
    ("ret_ytd", "Year-to-Date Return", "Ret YTD"),
    ("ret_mtd", "Month-to-Date Return", "Ret MTD"),
)
_VOL_DEFS: tuple[tuple[str, str, str], ...] = (
    ("vol_1m", "1-Month Volatility (annualized)", "Vol 1M"),
    ("vol_3m", "3-Month Volatility (annualized)", "Vol 3M"),
    ("vol_6m", "6-Month Volatility (annualized)", "Vol 6M"),
    ("vol_1y", "1-Year Volatility (annualized)", "Vol 1Y"),
)
_BETA_DEFS: tuple[tuple[str, str, str], ...] = (
    ("beta_3m_spy", "3-Month Beta vs SPY", "Beta 3M"),
    ("beta_6m_spy", "6-Month Beta vs SPY", "Beta 6M"),
    ("beta_1y_spy", "1-Year Beta vs SPY", "Beta 1Y"),
    ("beta_2y_spy", "2-Year Beta vs SPY", "Beta 2Y"),
)
_CORR_DEFS: tuple[tuple[str, str, str], ...] = (
    ("corr_spy", "1-Year Correlation vs SPY (US equities)", "Corr SPY"),
    ("corr_gld", "1-Year Correlation vs GLD (gold)", "Corr GLD"),
    ("corr_agg", "1-Year Correlation vs AGG (US bonds)", "Corr AGG"),
    ("corr_tlt", "1-Year Correlation vs TLT (long treasuries)", "Corr TLT"),
    ("corr_uso", "1-Year Correlation vs USO (oil)", "Corr USO"),
)
_SMA_DEFS: tuple[tuple[str, str, str], ...] = (
    ("pct_above_sma20", "Price Above/Below 20-Day SMA", "% SMA20"),
    ("pct_above_sma50", "Price Above/Below 50-Day SMA", "% SMA50"),
    ("pct_above_sma200", "Price Above/Below 200-Day SMA", "% SMA200"),
)


def _family(
    defs: tuple[tuple[str, str, str], ...],
    category: str,
    sub_category: str,
    data_type: DataType,
    scale_note: str,
    presets: tuple[PresetBand, ...],
) -> tuple[MetricDef, ...]:
    return tuple(
        MetricDef(code, name, abbr, category, sub_category, data_type, scale_note, presets)
        for code, name, abbr in defs
    )


CATALOG: tuple[MetricDef, ...] = (
    # --- Price ---
    *_family(_RETURN_DEFS, "Price", "Returns", "percent", _FRACTION_NOTE, _RETURN_PRESETS),
    MetricDef(
        "price_close", "Last Close Price", "Price", "Price", "Level",
        "currency", _CURRENCY_NOTE + " Raw (unadjusted) close.", _PRICE_PRESETS,
    ),
    MetricDef(
        "avg_volume_1m", "Average Daily Volume (1M)", "Avg Vol", "Price", "Liquidity",
        "int", "Shares per day, averaged over the trailing month.", _VOLUME_PRESETS,
    ),
    # --- Technicals: Statistics ---
    *_family(
        _VOL_DEFS, "Technicals: Statistics", "Volatility",
        "percent", _FRACTION_NOTE, _VOL_PRESETS,
    ),
    *_family(
        _BETA_DEFS, "Technicals: Statistics", "Beta",
        "float", _RATIO_NOTE, _BETA_PRESETS,
    ),
    *_family(
        _CORR_DEFS, "Technicals: Statistics", "Correlation",
        "float", _RATIO_NOTE + " Bounded in [-1, 1].", _CORR_PRESETS,
    ),
    # --- Indicator ---
    *_family(
        _SMA_DEFS, "Indicator", "Moving Averages",
        "percent", _FRACTION_NOTE + " close/SMA - 1.", _RETURN_PRESETS,
    ),
    # --- Fundamentals: Valuation ---
    MetricDef(
        "market_cap", "Market Capitalization", "Mkt Cap", "Fundamentals: Valuation", "Size",
        "currency", _CURRENCY_NOTE + " shares_outstanding x raw close.", _MARKET_CAP_PRESETS,
    ),
    MetricDef(
        "pe_ratio", "Price / Earnings (TTM)", "P/E", "Fundamentals: Valuation", "Multiples",
        "float", _RATIO_NOTE + " NULL when trailing net income <= 0.", _PE_PRESETS,
    ),
    MetricDef(
        "de_ratio", "Debt / Equity", "D/E", "Fundamentals: Valuation", "Leverage",
        "float", _RATIO_NOTE + " (total_assets - book_equity) / book_equity.", _DE_PRESETS,
    ),
    # --- Efficiency ---
    MetricDef(
        "roe", "Return on Equity (TTM)", "ROE", "Efficiency", "Profitability",
        "percent", _FRACTION_NOTE, _MARGIN_PRESETS,
    ),
    MetricDef(
        "roa", "Return on Assets", "ROA", "Efficiency", "Profitability",
        "percent", _FRACTION_NOTE, _MARGIN_PRESETS,
    ),
    MetricDef(
        "gross_margin", "Gross Margin", "GM", "Efficiency", "Profitability",
        "percent", _FRACTION_NOTE, _MARGIN_PRESETS,
    ),
    MetricDef(
        "profitability_gross", "Gross Profitability (GP / Assets)", "GP/A",
        "Efficiency", "Profitability",
        "percent", _FRACTION_NOTE + " Carried from the mother DB.", _MARGIN_PRESETS,
    ),
    # --- Growth ---
    MetricDef(
        "investment_growth", "Investment Growth (Asset Growth)", "Inv Gr", "Growth", "Assets",
        "percent", _FRACTION_NOTE + " Carried from the mother DB.", _GROWTH_PRESETS,
    ),
)

CATALOG_BY_CODE: dict[str, MetricDef] = {metric.code: metric for metric in CATALOG}


def get_metric(code: str) -> MetricDef | None:
    """Catalog lookup by code — the ONLY way user input maps to a column."""
    return CATALOG_BY_CODE.get(code)


def _validate_catalog() -> None:
    """Fail loud at import on duplicate codes or codes without a real column.

    The duplicate check encodes the Tiingo-study lesson (their live catalog
    shipped metricCode ``percentAboveBelowSMA20`` twice).
    """
    codes = [metric.code for metric in CATALOG]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise RuntimeError(f"Duplicate metric codes in screener catalog: {duplicates}")
    table_columns = set(ScreenerMetrics.__table__.columns.keys())
    unknown = sorted(set(codes) - table_columns)
    if unknown:
        raise RuntimeError(
            f"Screener catalog codes without a screener_metrics column: {unknown}"
        )


_validate_catalog()
