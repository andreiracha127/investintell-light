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

# Authorized proxy fill for a floored sleeve with no eligible fund: gold has no
# fund label at all; long_short has few funds. NO hedge (SH research-only).
GROUP_PROXY_FILL: dict[str, list[str]] = {"gold": ["GLD"], "long_short": ["FTLS"]}

# The lenient 4-class fallback (production ``load_fund_asset_class`` taxonomy).
_FALLBACK_CLASSES = frozenset({"cash", "equity", "fixed_income", "alternatives"})


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
    if strategy_label and strategy_label in LABEL_TO_GROUP:
        return LABEL_TO_GROUP[strategy_label]
    if asset_class and asset_class in _FALLBACK_CLASSES:
        return asset_class
    return "equity"
