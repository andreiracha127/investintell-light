"""Response schemas for GET /macro/regional and /macro/global-indicators.

Mirrors the version-1 macro_regional_snapshots.data_json materialized by the
macro_ingestion worker. dimensions/data_freshness are open maps because the
worker's indicator keys vary by region/vintage (free-form series_id → score):
US growth carries CFNAI/INDPRO/PAYEMS; the BIS credit_cycle dimension carries
credit_gap/debt_service/property_prices; the IMF-blended fiscal dimension carries
fiscal_balance/government_debt (see macro_ingestion._enrich_region).
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel


class DimensionOut(BaseModel):
    score: float  # 0-100 composite of indicators in this dimension
    n_indicators: int
    indicators: dict[str, float]  # series_id → 0-100 percentile-rank score


class DataFreshnessOut(BaseModel):
    last_date: dt.date | None
    days_stale: int | None
    weight: float  # 0.0-1.0 staleness-adjusted weight
    status: Literal["fresh", "decaying", "stale"]


class RegionScorecardOut(BaseModel):
    region: str  # 'US' | 'EUROPE' | 'ASIA' | 'EM'
    composite_score: float  # 0-100 (50 = historical median; neutral on low coverage)
    coverage: float  # 0-1 fraction of total dimension weight with data
    dimensions: dict[str, DimensionOut]
    data_freshness: dict[str, DataFreshnessOut]


class MacroRegionalResponse(BaseModel):
    """Latest regional macro scorecards (worker macro_ingestion, DB-first)."""

    as_of_date: dt.date
    regions: dict[str, RegionScorecardOut]


class GlobalIndicatorsResponse(BaseModel):
    """Global macro risk indicators (0-100). Note: polarity varies by field —
    geopolitical_risk_score and energy_stress are risk measures (higher = worse),
    while commodity_stress and usd_strength reflect market stress/strength."""

    as_of_date: dt.date
    geopolitical_risk_score: float
    energy_stress: float
    commodity_stress: float
    usd_strength: float
