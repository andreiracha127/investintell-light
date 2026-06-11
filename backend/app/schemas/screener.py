"""Request/response schemas for the screener endpoints (F6.4).

Scale contract (project-wide): preset/filter bounds are in the SAME unit as
the stored metric — "percent" metrics are decimal fractions (0.05 = 5%),
never 0-100.

Distribution contract (from the Tiingo screener study): the backend serves
``counts`` plus ``counts_normalized`` in 0..1 (count / max count) — NEVER
pixel heights; the frontend owns rendering scale.
"""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_NAME_LENGTH = 80


def _validate_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise ValueError(
            f"Screen name must be 1..{MAX_NAME_LENGTH} characters after trimming; "
            f"got {len(name)}."
        )
    return name


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class PresetBandOut(BaseModel):
    """One selectable filter band; null bound = unbounded on that side."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    min_value: float | None
    max_value: float | None


class MetricDefOut(BaseModel):
    """One catalog metric — ``code`` is the screener_metrics column name."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    abbreviation: str
    category: str
    sub_category: str
    data_type: str
    scale_note: str
    presets: list[PresetBandOut]


# ---------------------------------------------------------------------------
# Screen CRUD
# ---------------------------------------------------------------------------


class ScreenCreate(BaseModel):
    """Body for POST /screener/screens."""

    name: str = Field(
        description=f"Screen name; 1..{MAX_NAME_LENGTH} characters after trimming, "
        "unique across the installation."
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)


class ScreenPatch(BaseModel):
    """Body for PATCH /screener/screens/{id} — rename only."""

    name: str = Field(description="New screen name (same rules as on create).")

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)


class FilterBody(BaseModel):
    """Bounds for PUT /screener/screens/{id}/filters/{metric_code}.

    Both bounds null is legitimate: the metric is selected (results column,
    NULL exclusion) without numeric constraints.
    """

    min_value: float | None = Field(
        default=None, allow_inf_nan=False, description="Lower bound; null = unbounded."
    )
    max_value: float | None = Field(
        default=None, allow_inf_nan=False, description="Upper bound; null = unbounded."
    )

    @model_validator(mode="after")
    def _check_bounds(self) -> "FilterBody":
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError(
                f"min_value ({self.min_value}) must be <= max_value ({self.max_value})."
            )
        return self


class ScreenFilterOut(BaseModel):
    """One persisted filter row."""

    model_config = ConfigDict(from_attributes=True)

    metric_code: str
    min_value: float | None
    max_value: float | None
    position: int


class ScreenOut(BaseModel):
    """One screen with its filters (position order)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: dt.datetime
    updated_at: dt.datetime
    filters: list[ScreenFilterOut]


class ScreenListItem(BaseModel):
    """Row for GET /screener/screens."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filter_count: int
    created_at: dt.datetime
    updated_at: dt.datetime


# ---------------------------------------------------------------------------
# Build (distribution + headline count)
# ---------------------------------------------------------------------------


class DistributionOut(BaseModel):
    """Histogram over the active universe; counts_normalized in 0..1, never pixels."""

    model_config = ConfigDict(from_attributes=True)

    bin_edges: list[float] = Field(description="len(counts) + 1 edges; log-spaced for currency.")
    counts: list[int]
    counts_normalized: list[float] = Field(description="counts / max(counts), in 0..1.")


class BuildResponse(BaseModel):
    """GET /screener/screens/{id}/build/{metric_code}."""

    distribution: DistributionOut
    headline_count: int = Field(
        description="Universe rows satisfying ALL the screen's current filters."
    )
    available_count: int = Field(
        description=(
            "Non-NULL rows for this metric over the active universe. "
            "Distinguishes 'zero matches' (headline_count=0, available_count>0) "
            "from 'no data yet' (available_count=0) without inspecting the 422."
        )
    )


class FilterUpdateResponse(BaseModel):
    """PUT/DELETE filter response — one round-trip powers the Build UI.

    ``distribution`` is null (rather than failing the successful write with
    422) when the metric has zero non-NULL rows in the snapshot.
    ``available_count`` exposes the non-NULL count so the UI can distinguish
    "0 matches" from "no data" without relying solely on the 422 path.
    """

    screen: ScreenOut
    distribution: DistributionOut | None
    headline_count: int
    available_count: int = Field(
        description=(
            "Non-NULL rows for this metric over the active universe. "
            "0 implies the snapshot has not been computed yet."
        )
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class ResultsColumnOut(BaseModel):
    """One results-table column (ticker/name are data_type 'string')."""

    code: str
    name: str
    data_type: str


class ScreenResultsResponse(BaseModel):
    """GET /screener/screens/{id}/results — dynamic, whitelisted columns."""

    columns: list[ResultsColumnOut]
    rows: list[dict[str, str | float | None]]
    total: int
    page: int
    page_size: int
