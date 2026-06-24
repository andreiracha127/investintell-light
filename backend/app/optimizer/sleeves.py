"""Category-proxy / 7-sleeve model for the ``regime_aware`` two-level allocator
(COMBO S4b).

A fund's ``strategy_label`` (the catalog's 28+ category taxonomy) maps to a
category proxy ETF and one of the 7 base sleeves. The Level-1 solve optimizes
per-sleeve weights over the canonical ``GROUP_BENCHMARK`` proxies inside the
per-profile ``taa_bands`` envelope; the Level-2 implements each sleeve with its
selected funds EQUAL-WEIGHT (tracking the proxy, no re-optimization). Ported from
the calibrated harness (``scripts/local_fund_backtest.py``) and validated against
the production catalog (``funds_v.strategy_label`` — every label below is present;
the excluded ones — Balanced / Target Date / Defined Outcome / Leveraged / Crypto
/ Unclassified — fall back to ``asset_class``).
"""

from __future__ import annotations

from dataclasses import dataclass

MAPPING_VERSION = "regime-category-map-v1"


@dataclass(frozen=True)
class CategorySpec:
    """Stable economic category used by the regime-aware two-level compiler."""

    category_id: str
    sleeve_id: str
    benchmark_ticker: str
    display_label: str
    strategy_aliases: tuple[str, ...]
    mapping_version: str = MAPPING_VERSION

# strategy_label -> category proxy ETF. Labels outside the sleeve design
# (Balanced/Target Date/Defined Outcome/Leveraged/Crypto/Unclassified/Multi-Asset
# blends) are intentionally absent -> they resolve via ``asset_class``.
LABEL_TO_PROXY: dict[str, str] = {
    "Cash Equivalent": "BIL", "Government Money Market": "BIL",
    "Large Blend": "IVV", "Large Growth": "QQQ", "Large Value": "VOOV",
    "Mid Blend": "SCHM", "Mid Growth": "IWP", "Mid Value": "IWS",
    "Small Blend": "IWM", "Small Growth": "IWO", "Small Value": "IWN",
    "International Equity": "IEFA", "Emerging Markets Equity": "IEMG",
    "Global Equity": "VT", "ESG/Sustainable Equity": "ESGV",
    "Asian Equity": "AAXJ", "European Equity": "FEZ",
    "Size-Focused Equity": "IVV", "Index / Passive": "IVV",
    "Technology": "XLK", "Energy Equity": "XLE", "Health Care Equity": "XLV",
    "Financials Equity": "XLF", "Industrials Equity": "XLI",
    "Infrastructure Equity": "IFRA", "Materials Equity": "XLB",
    "Natural Resources Equity": "GUNR", "Consumer Discretionary Equity": "XLY",
    "Biotechnology Equity": "IBB", "Utilities Equity": "XLU",
    "Communication Services Equity": "XLC", "Consumer Staples Equity": "XLP",
    "Sector Rotation Equity": "EQL", "Clean Energy Equity": "ICLN",
    "Investment Grade Bond": "LQD", "Government Bond": "GOVT",
    "High Yield Bond": "HYG", "Municipal Bond": "MUB",
    "ESG/Sustainable Bond": "VCEB", "Intermediate-Term Bond": "BND",
    "Emerging Markets Debt": "EMB", "Structured Credit": "PAAA",
    "Mortgage-Backed Securities": "MBB", "Preferred Securities": "PFF",
    "Asset-Backed Securities": "DEED", "Convertible Securities": "ICVT",
    "Inflation-Linked Bond": "TIP", "Private Credit": "BIZD",
    "Real Estate": "VNQ", "Commodities": "GCC", "Alternative": "QAI",
    "Multi-Asset": "AOR", "Precious Metals": "RING",
    "Long/Short Equity": "FTLS",
}

# proxy ETF -> base sleeve. SH/'hedge' are NOT structural sleeves and are retired
# from the map (research-only, excluded from the standard book — freeze §13); GLD
# is the gold sleeve (no fund label maps to it — gold enters only via
# GROUP_PROXY_FILL).
PROXY_TO_GROUP: dict[str, str] = {
    "BIL": "cash",
    "IVV": "equity", "QQQ": "equity", "VOOV": "equity", "SCHM": "equity",
    "IWP": "equity", "IWS": "equity", "IWM": "equity", "IWO": "equity",
    "IWN": "equity", "IEFA": "equity", "IEMG": "equity", "VT": "equity",
    "ESGV": "equity", "AAXJ": "equity", "FEZ": "equity",
    "XLK": "thematic", "XLE": "thematic", "XLV": "thematic", "XLF": "thematic",
    "XLI": "thematic", "IFRA": "thematic", "XLB": "thematic", "GUNR": "thematic",
    "XLY": "thematic", "IBB": "thematic", "XLU": "thematic", "XLC": "thematic",
    "XLP": "thematic", "EQL": "thematic", "ICLN": "thematic",
    "LQD": "fixed_income", "GOVT": "fixed_income", "HYG": "fixed_income",
    "MUB": "fixed_income", "VCEB": "fixed_income", "BND": "fixed_income",
    "EMB": "fixed_income", "PAAA": "fixed_income", "MBB": "fixed_income",
    "PFF": "fixed_income", "DEED": "fixed_income", "ICVT": "fixed_income",
    "TIP": "fixed_income", "BIZD": "fixed_income",
    "VNQ": "alternatives", "GCC": "alternatives", "QAI": "alternatives",
    "AOR": "alternatives", "RING": "alternatives",
    "FTLS": "long_short", "GLD": "gold",
}

LABEL_TO_GROUP: dict[str, str] = {
    lb: PROXY_TO_GROUP[px] for lb, px in LABEL_TO_PROXY.items()
}

# The 7 base sleeves the Level-1 solve allocates over (mirrors
# ``taa_bands.SLEEVE_GROUPS``). 'hedge' is excluded by design.
SLEEVE_GROUPS: list[str] = [
    "cash", "equity", "fixed_income", "thematic", "alternatives", "gold", "long_short",
]

# One canonical benchmark proxy per sleeve — the Level-1 instrument.
GROUP_BENCHMARK: dict[str, str] = {
    "cash": "BIL", "equity": "IVV", "fixed_income": "GOVT", "thematic": "XLK",
    "alternatives": "QAI", "gold": "GLD", "long_short": "FTLS",
}

_CATEGORY_ID_BY_PROXY: dict[str, str] = {
    "BIL": "CASH_USD/BIL",
    "IVV": "EQUITY_US_LARGE/IVV",
    "QQQ": "EQUITY_US_GROWTH/QQQ",
    "VOOV": "EQUITY_US_VALUE/VOOV",
    "SCHM": "EQUITY_US_MID/SCHM",
    "IWP": "EQUITY_US_MID_GROWTH/IWP",
    "IWS": "EQUITY_US_MID_VALUE/IWS",
    "IWM": "EQUITY_US_SMALL/IWM",
    "IWO": "EQUITY_US_SMALL_GROWTH/IWO",
    "IWN": "EQUITY_US_SMALL_VALUE/IWN",
    "IEFA": "EQUITY_INTL_DEVELOPED/IEFA",
    "IEMG": "EQUITY_EMERGING/IEMG",
    "VT": "EQUITY_GLOBAL/VT",
    "ESGV": "EQUITY_ESG/ESGV",
    "AAXJ": "EQUITY_ASIA/AAXJ",
    "FEZ": "EQUITY_EUROPE/FEZ",
    "XLK": "THEMATIC_TECH/XLK",
    "XLE": "THEMATIC_ENERGY/XLE",
    "XLV": "THEMATIC_HEALTHCARE/XLV",
    "XLF": "THEMATIC_FINANCIALS/XLF",
    "XLI": "THEMATIC_INDUSTRIALS/XLI",
    "IFRA": "THEMATIC_INFRASTRUCTURE/IFRA",
    "XLB": "THEMATIC_MATERIALS/XLB",
    "GUNR": "THEMATIC_NATURAL_RESOURCES/GUNR",
    "XLY": "THEMATIC_CONSUMER_DISCRETIONARY/XLY",
    "IBB": "THEMATIC_BIOTECH/IBB",
    "XLU": "THEMATIC_UTILITIES/XLU",
    "XLC": "THEMATIC_COMMUNICATIONS/XLC",
    "XLP": "THEMATIC_CONSUMER_STAPLES/XLP",
    "EQL": "THEMATIC_SECTOR_ROTATION/EQL",
    "ICLN": "THEMATIC_CLEAN_ENERGY/ICLN",
    "LQD": "FIXED_INCOME_IG_CREDIT/LQD",
    "GOVT": "FIXED_INCOME_US_GOVT/GOVT",
    "HYG": "FIXED_INCOME_HIGH_YIELD/HYG",
    "MUB": "FIXED_INCOME_MUNICIPAL/MUB",
    "VCEB": "FIXED_INCOME_ESG/VCEB",
    "BND": "FIXED_INCOME_CORE/BND",
    "EMB": "FIXED_INCOME_EM_DEBT/EMB",
    "PAAA": "FIXED_INCOME_STRUCTURED/PAAA",
    "MBB": "FIXED_INCOME_MBS/MBB",
    "PFF": "FIXED_INCOME_PREFERRED/PFF",
    "DEED": "FIXED_INCOME_ABS/DEED",
    "ICVT": "FIXED_INCOME_CONVERTIBLE/ICVT",
    "TIP": "FIXED_INCOME_TIPS/TIP",
    "BIZD": "FIXED_INCOME_PRIVATE_CREDIT/BIZD",
    "VNQ": "ALTERNATIVES_REAL_ESTATE/VNQ",
    "GCC": "ALTERNATIVES_COMMODITIES/GCC",
    "QAI": "ALTERNATIVES_MULTI_STRATEGY/QAI",
    "AOR": "ALTERNATIVES_MULTI_ASSET/AOR",
    "RING": "ALTERNATIVES_PRECIOUS_METALS/RING",
    "GLD": "GOLD/GLD",
    "FTLS": "LONG_SHORT_EQUITY/FTLS",
}

_DISPLAY_LABEL_BY_PROXY: dict[str, str] = {
    proxy: category_id.split("/", 1)[0].replace("_", " ").title()
    for proxy, category_id in _CATEGORY_ID_BY_PROXY.items()
}


def _aliases_by_proxy() -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {proxy: [] for proxy in PROXY_TO_GROUP}
    for label, proxy in LABEL_TO_PROXY.items():
        aliases.setdefault(proxy, []).append(label)
    return aliases


_ALIASES_BY_PROXY = _aliases_by_proxy()

CATEGORY_SPECS: tuple[CategorySpec, ...] = tuple(
    CategorySpec(
        category_id=_CATEGORY_ID_BY_PROXY[proxy],
        sleeve_id=PROXY_TO_GROUP[proxy],
        benchmark_ticker=proxy,
        display_label=_DISPLAY_LABEL_BY_PROXY[proxy],
        strategy_aliases=tuple(sorted(_ALIASES_BY_PROXY.get(proxy, []))),
    )
    for proxy in sorted(PROXY_TO_GROUP)
)

CATEGORY_BY_PROXY: dict[str, CategorySpec] = {
    spec.benchmark_ticker: spec for spec in CATEGORY_SPECS
}
CATEGORY_BY_STRATEGY_ALIAS: dict[str, CategorySpec] = {
    alias: spec for spec in CATEGORY_SPECS for alias in spec.strategy_aliases
}

# Authorized proxy fills for ``complete_macro``. These are the only proxies the
# backend may activate when an economic sleeve needs an implementation. NO hedge
# (SH research-only).
GROUP_PROXY_FILL: dict[str, list[str]] = {
    "cash": ["BIL"],
    "equity": ["IVV"],
    "fixed_income": ["GOVT", "LQD", "HYG", "TIP", "BND"],
    "thematic": ["XLK"],
    "alternatives": ["QAI"],
    "gold": ["GLD"],
    "long_short": ["FTLS"],
}

# The lenient 4-class fallback (production ``load_fund_asset_class`` taxonomy).
_FALLBACK_CLASSES = frozenset({"cash", "equity", "fixed_income", "alternatives"})


def category_for_proxy(proxy: str) -> CategorySpec:
    """Resolve an authorized proxy ticker to its canonical category."""
    ticker = proxy.upper()
    if ticker in CATEGORY_BY_PROXY:
        return CATEGORY_BY_PROXY[ticker]
    return CATEGORY_BY_PROXY[GROUP_BENCHMARK["equity"]]


def category_for_fund(
    strategy_label: str | None, asset_class: str | None
) -> CategorySpec:
    """Resolve fund taxonomy to a stable economic category.

    Fine-grained strategy aliases win. Unknown labels fall back to the lenient
    4-class asset class. Inverse / Hedge and SH are intentionally absent from the
    taxonomy, so they never become policy-core categories.
    """
    if strategy_label and strategy_label in CATEGORY_BY_STRATEGY_ALIAS:
        return CATEGORY_BY_STRATEGY_ALIAS[strategy_label]
    if asset_class and asset_class in _FALLBACK_CLASSES:
        return CATEGORY_BY_PROXY[GROUP_BENCHMARK[asset_class]]
    return CATEGORY_BY_PROXY[GROUP_BENCHMARK["equity"]]


def fund_sleeve_group(strategy_label: str | None, asset_class: str | None) -> str:
    """Resolve a fund to one sleeve.

    Precedence: the fine-grained ``strategy_label`` (via ``LABEL_TO_GROUP``) wins;
    else the 4-class ``asset_class`` (equity/fixed_income/alternatives/cash); else
    ``"equity"`` (raw equities carry no asset_class; unknown labels are equity-like).
    ``"Inverse / Hedge"`` is no longer mapped (SH/hedge retired — research-only,
    freeze §13), so it falls through to the asset_class/equity default and never
    produces a ``"hedge"`` sleeve. ``"gold"`` is never produced here (no label maps
    to GLD); it enters only via ``GROUP_PROXY_FILL``.
    """
    return category_for_fund(strategy_label, asset_class).sleeve_id
