"""Request/response schemas for the fund universe endpoints (F8.2).

Scale contract (project-wide): percent-like values are decimal fractions
(0.05 = 5%), copied verbatim from the mother DB — the Light NEVER recomputes.

Classification caveat (mother-DB inventory 2026-06-11): `strategy_label`
largely comes from the source's automatic description classifier, which has
visible errors. Every list/profile response carries a fixed
``classification_note`` so the UI can disclaim it.
"""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, field_validator

# Fixed disclaimer — the sync mirrors the source faithfully and we do not
# store per-row provenance, so the caveat applies to the whole column.
CLASSIFICATION_NOTE = (
    "Labels da fonte podem conter erros do classificador automático"
)

# Adviser names arrive ALL-CAPS from the Form ADV (sec_managers) source. We
# present them in title case for legibility. Legal-suffix / abbreviation tokens
# stay upper-case; small connectors stay lower-case.
_MANAGER_KEEP_UPPER = frozenset({
    "LLC", "LP", "LLP", "PLC", "LTD", "NA", "USA", "US", "UK", "ETF", "REIT",
    "SA", "AG", "NV", "II", "III", "IV", "&", "DBA", "TIAA-CREF", "PIMCO",
})
_MANAGER_KEEP_LOWER = frozenset({"and", "of", "the", "for", "de", "da", "to", "in"})


def format_company_name(name: str | None) -> str | None:
    """Title-case an ALL-CAPS company name for display (pure — unit-tested).

    Names that already carry mixed case (e.g. the N-CEN source) are trusted and
    returned unchanged. For all-caps input, each word is capitalized, except:
    known abbreviations (LLC, LP, &, US…) stay upper; connectors (and, of…) stay
    lower; and short dotted initials (J.P., T.) keep their case.
    """
    if not name:
        return name
    if not name.isupper():
        return name
    words = name.split()
    out: list[str] = []
    for index, word in enumerate(words):
        bare = word.strip(".,").upper()
        letters = bare.replace(".", "").replace("&", "")
        if bare in _MANAGER_KEEP_UPPER:
            out.append(word)
        elif "." in word and len(letters) <= 2:
            out.append(word)  # initials: J.P., T.
        elif index > 0 and bare.lower() in _MANAGER_KEEP_LOWER:
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


class FundsStaleness(BaseModel):
    """Global data-freshness markers (max over the synced universe)."""

    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None


class FundListItem(BaseModel):
    """One row of the funds table: identity + headline risk metrics."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    series_id: str
    ticker: str | None
    name: str
    fund_type: str
    strategy_label: str
    asset_class: str | None
    is_index: bool | None
    expense_ratio: float | None
    aum_usd: float | None
    return_1y: float | None
    volatility_1y: float | None
    sharpe_1y: float | None
    max_drawdown_1y: float | None
    peer_sharpe_pctl: float | None
    manager_score: float | None
    elite_flag: bool | None
    # Investment adviser, resolved per page from the N-CEN crosswalk
    # (series_id -> sec_fund_adviser -> sec_managers firm name via CRD); not
    # stored in the list MV. None when the fund has no resolved adviser.
    # Presented in title case (the Form ADV source is ALL-CAPS).
    manager_name: str | None = None

    @field_validator("manager_name")
    @classmethod
    def _title_case_manager(cls, value: str | None) -> str | None:
        return format_company_name(value)


class FundsListResponse(BaseModel):
    items: list[FundListItem]
    total: int
    page: int
    page_size: int
    staleness: FundsStaleness
    classification_note: str = CLASSIFICATION_NOTE


class FundRiskOut(BaseModel):
    """The full precomputed risk snapshot (latest calc_date in the source)."""

    model_config = ConfigDict(from_attributes=True)

    calc_date: dt.date
    return_1m: float | None
    return_3m: float | None
    return_1y: float | None
    return_3y_ann: float | None
    return_5y_ann: float | None
    volatility_1y: float | None
    max_drawdown_1y: float | None
    max_drawdown_3y: float | None
    sharpe_1y: float | None
    sharpe_3y: float | None
    sortino_1y: float | None
    calmar_ratio_3y: float | None
    alpha_1y: float | None
    beta_1y: float | None
    information_ratio_1y: float | None
    tracking_error_1y: float | None
    var_95_1m: float | None
    cvar_95_1m: float | None
    cvar_95_12m: float | None
    cvar_99_evt: float | None
    cvar_999_evt: float | None
    evt_xi_shape: float | None
    volatility_garch: float | None
    vol_model: str | None
    peer_strategy_label: str | None
    peer_sharpe_pctl: float | None
    peer_sortino_pctl: float | None
    peer_return_pctl: float | None
    peer_drawdown_pctl: float | None
    peer_count: int | None
    manager_score: float | None
    elite_flag: bool | None
    downside_capture_1y: float | None
    upside_capture_1y: float | None
    equity_correlation_252d: float | None
    # Class-specific regression metrics (dimensionless betas / decimal fractions).
    empirical_duration: float | None = None
    credit_beta: float | None = None
    inflation_beta: float | None = None
    crisis_alpha_score: float | None = None


class FundBenchmarkOut(BaseModel):
    """Benchmark candidate resolved from SEC metadata plus canonical ETF proxy map."""

    name: str | None
    proxy_ticker: str | None
    proxy_instrument_id: uuid.UUID | None
    proxy_fit_quality_score: float | None
    proxy_asset_class: str | None
    resolution_method: str | None
    resolution_conflict: bool
    proxy_candidates: list[str] = []
    canonical_name_matches: list[str] = []


class FundClassOut(BaseModel):
    """One share class of the fund's series (F8.6b).

    NOTE: only the series' representative class has a NAV in the source —
    any class ticker is priced/analyzed with the SERIES NAV as a proxy.
    ``expense_ratio`` is a fraction (0.0069 = 0.69%).
    """

    model_config = ConfigDict(from_attributes=True)

    class_id: str
    class_name: str | None
    ticker: str
    expense_ratio: float | None


class FundNavPoint(BaseModel):
    """One decimated NAV observation (last 2 years, ~260 points)."""

    date: dt.date
    nav: float | None


class FundHoldingItem(BaseModel):
    """One N-PORT holding row. ⚠️ ``pct_of_nav`` is in PERCENT units in the
    source (11.62 = 11.62%) — unlike the risk metrics, which are fractions."""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    issuer_name: str | None
    cusip: str | None
    isin: str | None
    asset_class: str | None
    # N-PORT issuerCat code (CORP/UST/MUN...) — kept for completeness.
    sector: str | None
    # Real GICS sector (sec_cusip_ticker_map); the UI's "Sector" column.
    gics_sector: str | None
    market_value: float | None
    pct_of_nav: float | None


class FundHoldingsOut(BaseModel):
    """Latest N-PORT report for the fund's series (full, untruncated source).

    The profile still serves a display-capped list (HOLDINGS_CAP); the
    consolidated exposure lives in GET /funds/{id}/lookthrough (Frente C).
    """

    report_date: dt.date | None
    items: list[FundHoldingItem]
    # Sum of the reported pct_of_nav (percent units) over the returned items.
    pct_of_nav_total: float | None


class FundProfileResponse(BaseModel):
    """Full fund profile: identity + all risk metrics + NAV series + holdings."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    series_id: str
    ticker: str | None
    isin: str | None
    cusip: str | None
    lei: str | None
    name: str
    fund_type: str
    strategy_label: str
    asset_class: str | None
    is_index: bool | None
    expense_ratio: float | None
    aum_usd: float | None
    primary_benchmark: str | None
    benchmark: FundBenchmarkOut | None = None
    inception_date: dt.date | None
    domicile: str | None
    currency: str | None
    # Staleness markers — now derived from the dynamic sources (the funds_v VIEW
    # has no sync columns), hence nullable like FundsStaleness (Task 2.3/2.4).
    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None
    risk: FundRiskOut | None
    nav: list[FundNavPoint]
    holdings: FundHoldingsOut
    # Share classes, expense_ratio asc NULLS LAST (F8.6b).
    classes: list[FundClassOut]
    classification_note: str = CLASSIFICATION_NOTE
