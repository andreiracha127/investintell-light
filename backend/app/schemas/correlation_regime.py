"""Schemas for POST /correlation-regime (T3F).

Scale contract: correlations, ratios and the diversification ratio are decimal
fractions / pure numbers (never 0-100). The request mirrors the builder's
explicit-``assets``-OR-``universe`` shape (app.schemas.builder) so the route
reuses the same fund/equity selection semantics.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.builder import AssetRefIn, UniverseSpecIn


class PairCorrelationOut(BaseModel):
    label_a: str
    label_b: str
    current_correlation: float
    baseline_correlation: float
    correlation_change: float
    is_contagion: bool


class ConcentrationOut(BaseModel):
    eigenvalues: list[float]
    first_eigenvalue_ratio: float
    concentration_status: Literal[
        "diversified", "moderate_concentration", "high_concentration"
    ]
    absorption_ratio: float
    absorption_status: Literal["normal", "warning", "critical"]
    mp_threshold: float  # Marchenko-Pastur upper bound λ₊
    n_signal_eigenvalues: int


class CorrelationRegimeOut(BaseModel):
    instrument_count: int
    labels: list[str]
    window_days: int
    correlation_matrix: list[list[float]]
    pair_correlations: list[PairCorrelationOut]
    concentration: ConcentrationOut
    diversification_ratio: float
    dr_alert: bool
    average_correlation: float
    baseline_average_correlation: float
    regime_shift_detected: bool
    sufficient_data: bool


class CorrelationRegimeRequest(BaseModel):
    """Analyze either an explicit ``assets`` list OR a ``universe`` spec
    (exactly one), over the optimizer's aligned returns matrix.
    """

    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)] | None = None
    universe: UniverseSpecIn | None = None
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None

    @model_validator(mode="after")
    def _check_source(self) -> "CorrelationRegimeRequest":
        if (self.assets is None) == (self.universe is None):
            raise ValueError(
                "provide exactly one of 'assets' (explicit list) or 'universe' "
                "(filter+rank the fund universe)"
            )
        return self
