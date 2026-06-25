"""T2F-1: the orphaned EVT/GARCH worker outputs must be surfaced through
FundRiskOut. The worker computes volatility_garch / vol_model / cvar_999_evt /
evt_xi_shape into fund_risk_metrics, but the MV-backed FundRiskLatest ORM and
FundRiskOut schema never exposed them. They are validated from attributes,
exactly as the profile route does (FundRiskOut.model_validate(profile.risk))."""

import datetime as dt

from app.models.fund import FundRiskLatest
from app.schemas.funds import FundRiskOut


class _RiskAttrs:
    """Minimal stand-in for a FundRiskLatest ORM row (from_attributes path)."""

    def __init__(self, **kwargs: object) -> None:
        # Every FundRiskOut field defaults to None; override the ones we test.
        for name in FundRiskOut.model_fields:
            setattr(self, name, None)
        self.calc_date = dt.date(2026, 6, 13)
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_fund_risk_out_declares_orphaned_worker_fields() -> None:
    fields = set(FundRiskOut.model_fields)
    assert {"volatility_garch", "vol_model", "cvar_999_evt", "evt_xi_shape"} <= fields


def test_fund_risk_out_tracks_full_latest_risk_snapshot() -> None:
    """Every scalar projected by fund_risk_latest_mv should be serializable.

    instrument_id is the route path key and organization_id is always NULL for
    the global latest snapshot; the API risk object exposes the remaining
    worker-owned scalar columns.
    """
    table_cols = {c.name for c in FundRiskLatest.__table__.columns}
    response_cols = set(FundRiskOut.model_fields)
    assert table_cols - {"instrument_id", "organization_id"} <= response_cols


def test_fund_risk_out_round_trips_orphaned_fields() -> None:
    attrs = _RiskAttrs(
        volatility_garch=0.1834,
        vol_model="GARCH(1,1)",
        cvar_999_evt=-0.0921,
        evt_xi_shape=0.213,
    )
    out = FundRiskOut.model_validate(attrs)
    assert out.volatility_garch == 0.1834
    assert out.vol_model == "GARCH(1,1)"
    assert out.cvar_999_evt == -0.0921
    assert out.evt_xi_shape == 0.213


def test_fund_risk_out_orphaned_fields_are_optional() -> None:
    """They are nullable in the source (per-metric gaps) — None must validate."""
    out = FundRiskOut.model_validate(_RiskAttrs())
    assert out.volatility_garch is None
    assert out.vol_model is None
    assert out.cvar_999_evt is None
    assert out.evt_xi_shape is None
