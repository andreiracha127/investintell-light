"""Response schemas for the look-through endpoints (Frente C).

All pct fields are PERCENT POINTS (50.0 = 50%), sign preserved, never
renormalized — they mirror the materialized tables computed by the
``nport_lookthrough`` worker in the datalake repo.
"""

import datetime as dt
import uuid
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

DimensionName = str  # 'issuer' | 'asset_class' | 'sector' | 'currency'


class ExposureItem(BaseModel):
    key: str
    label: str | None
    direct_pct: float
    indirect_pct: float
    total_pct: float


class LookthroughSummaryOut(BaseModel):
    """Residual explícito + proveniência (espelha nport_lookthrough_summary)."""

    sum_pct_total: float | None
    direct_pct: float | None
    indirect_pct: float | None
    expanded_fund_pct: float | None
    nondecomposable_fund_pct: float | None
    derivatives_gross_pct: float | None
    derivatives_net_pct: float | None
    unidentified_pct: float | None
    # Copiado de cagg_nport_series_profile pelo worker (nunca recalculado).
    coverage_pct: float | None
    n_holdings: int | None
    n_children_expanded: int | None
    # Staleness em cadeia: report N-PORT mais antigo usado na expansão.
    oldest_report_date: dt.date | None


class FundLookthroughResponse(BaseModel):
    instrument_id: uuid.UUID
    series_id: str
    report_date: dt.date
    dimensions: dict[DimensionName, list[ExposureItem]]
    summary: LookthroughSummaryOut


class UnexpandedPosition(BaseModel):
    """Posição não atravessada — residual explícito no nível do portfólio."""

    ticker: str
    weight_pct: float
    # 'not_a_fund' (ação/ETF fora do universo de fundos sincronizado) |
    # 'not_materialized' (fundo sem look-through materializado no data-lake).
    reason: str


def build_dimensions(
    rows: Iterable[Any], only: str | None = None
) -> dict[str, list[ExposureItem]]:
    """Group service ExposureRow-likes into the response dimensions dict.

    ``only`` restricts the dict to a single dimension (the ?dimension= query
    param); otherwise all four canonical dimensions are present (empty lists
    for dimensions with no rows — explicit, never omitted).
    """
    names = (only,) if only else ("issuer", "asset_class", "sector", "currency")
    dimensions: dict[str, list[ExposureItem]] = {name: [] for name in names}
    for row in rows:
        if row.dimension not in dimensions:
            continue
        dimensions[row.dimension].append(
            ExposureItem(
                key=row.key,
                label=row.label,
                direct_pct=row.direct_pct,
                indirect_pct=row.indirect_pct,
                total_pct=row.direct_pct + row.indirect_pct,
            )
        )
    for items in dimensions.values():
        items.sort(key=lambda item: -abs(item.total_pct))
    return dimensions


class PortfolioLookthroughResponse(BaseModel):
    portfolio_id: int
    total_value: float
    cash_weight_pct: float
    expanded_weight_pct: float
    # Σ ponderado dos sum_pct_total dos fundos expandidos (pontos do valor
    # total do portfólio) — pode passar de expanded_weight_pct quando há
    # alavancagem nos fundos; nunca renormalizado.
    sum_pct_total: float
    oldest_report_date: dt.date | None
    n_funds_expanded: int
    unexpanded: list[UnexpandedPosition]
    dimensions: dict[DimensionName, list[ExposureItem]]
