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
    blended_momentum_score: float | None = None
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
    cvar_95_1m: float | None
    cvar_95_3m: float | None = None
    cvar_95_6m: float | None = None
    cvar_95_12m: float | None
    var_95_1m: float | None
    var_95_3m: float | None = None
    var_95_6m: float | None = None
    var_95_12m: float | None = None
    return_1m: float | None
    return_3m: float | None
    return_6m: float | None = None
    return_1y: float | None
    return_3y_ann: float | None
    return_5y_ann: float | None
    return_10y_ann: float | None = None
    volatility_1y: float | None
    volatility_garch: float | None
    vol_model: str | None
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
    upside_capture_1y: float | None
    downside_capture_1y: float | None
    sharpe_cf: float | None = None
    sharpe_cf_skew: float | None = None
    sharpe_cf_kurt: float | None = None
    sharpe_cf_ci_lower: float | None = None
    sharpe_cf_ci_upper: float | None = None
    cvar_99_evt: float | None
    cvar_999_evt: float | None
    evt_xi_shape: float | None
    fed_funds_rate_at_calc: float | None = None
    data_quality_flags: dict[str, object] | None = None
    peer_strategy_label: str | None
    peer_sharpe_pctl: float | None
    peer_sortino_pctl: float | None
    peer_return_pctl: float | None
    peer_drawdown_pctl: float | None
    peer_count: int | None
    manager_score: float | None
    elite_flag: bool | None
    equity_correlation_252d: float | None
    active_share_normalized: float | None = None
    overlap_normalized: float | None = None
    overlap_nav_raw: float | None = None
    fund_cusip_coverage_nav: float | None = None
    benchmark_cusip_coverage_nav: float | None = None
    n_fund_holdings: int | None = None
    n_benchmark_holdings: int | None = None
    n_common_holdings: int | None = None
    n_fund_only: int | None = None
    n_benchmark_only: int | None = None
    holdings_jaccard: float | None = None
    fund_report_age_days: int | None = None
    benchmark_report_age_days: int | None = None
    report_date_gap_days: int | None = None
    active_share_benchmark_instrument_id: uuid.UUID | None = None
    active_share_benchmark_series_id: str | None = None
    active_share_fund_report_date: dt.date | None = None
    active_share_benchmark_report_date: dt.date | None = None
    score_components: dict[str, object] | None = None
    dtw_drift_score: float | None = None
    rsi_14: float | None = None
    bb_position: float | None = None
    nav_momentum_score: float | None = None
    flow_momentum_score: float | None = None
    blended_momentum_score: float | None = None
    cvar_95_conditional: float | None = None
    elite_rank_within_strategy: int | None = None
    elite_target_count_per_strategy: int | None = None
    yield_proxy_12m: float | None = None
    duration_adj_drawdown_1y: float | None = None
    scoring_model: str | None = None
    seven_day_net_yield: float | None = None
    nav_per_share_mmf: float | None = None
    pct_weekly_liquid: float | None = None
    weighted_avg_maturity_days: int | None = None
    peer_overall_quartile: int | None = None
    peer_band_low: float | None = None
    peer_band_mid: float | None = None
    peer_band_high: float | None = None
    nav_quality_ok: bool | None = None
    nav_glitch_count: int | None = None
    flow_momentum_as_of: dt.date | None = None
    flow_momentum_observation_count: int | None = None
    nport_flow_momentum_score: float | None = None
    nport_flow_as_of: dt.date | None = None
    nport_flow_staleness_days: int | None = None
    nport_flow_observation_count: int | None = None
    # Class-specific regression metrics (dimensionless betas / decimal fractions).
    empirical_duration: float | None = None
    empirical_duration_r2: float | None = None
    credit_beta: float | None = None
    credit_beta_r2: float | None = None
    inflation_beta: float | None = None
    inflation_beta_r2: float | None = None
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
    # Staleness markers — now derived from dynamic sources (funds_profile_mv has
    # no sync columns), hence nullable like FundsStaleness (Task 2.3/2.4).
    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None
    risk: FundRiskOut | None
    nav: list[FundNavPoint]
    holdings: FundHoldingsOut
    # Share classes, expense_ratio asc NULLS LAST (F8.6b).
    classes: list[FundClassOut]
    classification_note: str = CLASSIFICATION_NOTE
