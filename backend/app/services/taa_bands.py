"""Pure band-math service for the COMBO regime allocator (Sprint 2).

Ports the validated tactical-asset-allocation band logic from the Lean harness
``lean-research/TaaCvarSuite/main.py`` into a dependency-light backend module
(math + dataclasses + one async data-lake reader; NO cvxpy / engine import).
Sprint 3 wires these building blocks into the optimizer.

What is ported (and from which ``main.py`` symbol):

* ``compute_effective_band``                                (``main.py:252-267``)
* ``smooth_regime_centers``                                 (``main.py:270-285``)
* ``macro_quadrant_from_proxies`` ← ``_macro_quadrant``     (``main.py:710-739``)
  PARITY-ONLY (spec §9, decision A): the growth×inflation quadrant is
  MATERIALIZED by the ``regime_gate`` worker (Sprint 1) into
  ``regime_gate_daily.quadrant`` and READ here via ``fetch_gate_regime``; this
  pure classifier is kept for fidelity/unit-tests but is NOT on the runtime path.
* ``market_stress`` / ``asset_betas`` / ``vol_graduated_caps`` /
  ``beta_graduated_caps``                                   (``main.py:998-1061``)
* ``fetch_gate_regime`` — ``regime_gate_daily`` reader, mirroring
  ``macro_regime.fetch_composite_regime`` (``macro_regime.py:187-238``).

Task 8 (spec §I legados) RETIRED the legacy S4a band machinery now superseded by
``quadrant_policy.QUADRANT_POLICIES`` + ``policy_bands``: ``DEFAULT_TAA_BANDS`` /
``IPS_CLASS_BOUNDS`` / ``ASSET_CLASSES`` / ``HW_SCALE`` / ``SLEEVE_GROUPS`` /
``PROFILE_CENTERS`` / ``SLEEVE_HALF_WIDTHS`` / ``SLEEVE_IPS_BOUNDS``,
``band_state_from_quadrant`` / ``normalized_profile_centers`` /
``profile_sleeve_bands``, ``combined_regime`` / ``effective_class_bands`` and the
``goldfix_target`` haven. The per-instrument ``vol_graduated_caps`` /
``beta_graduated_caps`` throttles are KEPT (Plan C consumers).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── Validated constants ───────────────────────────────────────────────────────
EMA_HALFLIFE_DAYS = 5
MAX_DAILY_SHIFT = 0.03
G_LOOK = 126            # growth lookback (SPY 126d return sign).
I_LOOK = 126            # inflation lookback (TIP-IEF breakeven momentum).
GATE_DD = 0.06          # SPY 63d-drawdown gate threshold.
VG_BETA = 1.5           # vol-graduated-cap aggressiveness.
BG_COEF = 1.0           # beta-graduated-cap coefficient.


# ── taa_band_service.py port: band clamping + EMA smoothing ──────────────────
def compute_effective_band(
    ips_min: float, ips_max: float, regime_center: float, regime_half_width: float
) -> tuple[float, float]:
    """Clamp a regime ``center ± half_width`` band to the IPS hard bounds.

    Verbatim port of ``main.py:252-267``. When the regime band falls entirely
    outside the IPS window, snap to the nearer IPS edge and widen inward by
    ``2 * half_width`` (kept feasible against the far IPS edge).
    """
    regime_min = regime_center - regime_half_width
    regime_max = regime_center + regime_half_width
    effective_min = max(ips_min, regime_min)
    effective_max = min(ips_max, regime_max)
    if effective_min > effective_max:
        if regime_center < ips_min:
            effective_min = ips_min
            effective_max = min(ips_min + 2 * regime_half_width, ips_max)
        elif regime_center > ips_max:
            effective_max = ips_max
            effective_min = max(ips_max - 2 * regime_half_width, ips_min)
        else:
            effective_min = ips_min
            effective_max = ips_max
    return effective_min, effective_max


def smooth_regime_centers(
    current_centers: dict[str, float],
    previous_smoothed: dict[str, float] | None,
    *,
    halflife_days: int = EMA_HALFLIFE_DAYS,
    max_daily_shift: float = MAX_DAILY_SHIFT,
) -> dict[str, float]:
    """EMA-smooth class centers with a per-day max-shift clamp.

    Verbatim port of ``main.py:270-285``. On the first pass
    (``previous_smoothed is None``) returns a COPY of ``current_centers`` —
    the point-in-time builder path (``previous_smoothed=None``) thus gets the
    raw centers, faithful to the reference's first step.
    """
    if previous_smoothed is None:
        return dict(current_centers)
    alpha = 1 - math.exp(-math.log(2) / halflife_days)
    smoothed: dict[str, float] = {}
    for asset_class, target in current_centers.items():
        prev = previous_smoothed.get(asset_class, target)
        raw_smoothed = alpha * target + (1 - alpha) * prev
        delta = raw_smoothed - prev
        if abs(delta) > max_daily_shift:
            clamped = prev + max_daily_shift * (1 if delta > 0 else -1)
            smoothed[asset_class] = round(clamped, 6)
        else:
            smoothed[asset_class] = round(raw_smoothed, 6)
    return smoothed


# ── Growth × inflation clock (PARITY-ONLY — decision A, spec §9) ──────────────
def _pct_return(closes_desc: list[float], k: int) -> float | None:
    """``k``-period return from a NEWEST-FIRST close list.

    ``closes_desc[0]`` is "now", ``closes_desc[k]`` is "k periods ago". Returns
    ``None`` when there is insufficient history or the base is non-positive
    (matches ``ret_k`` in ``main.py:714-719``).
    """
    if len(closes_desc) <= k:
        return None
    now = closes_desc[0]
    then = closes_desc[k]
    return (now / then - 1.0) if then > 0 else None


def macro_quadrant_from_proxies(
    spy_desc: list[float],
    tip_desc: list[float],
    ief_desc: list[float],
    *,
    g_look: int = G_LOOK,
    i_look: int = I_LOOK,
) -> dict[str, Any] | None:
    """Classify the growth × inflation quadrant from price proxies.

    PARITY-ONLY (spec §9, decision A): ported + unit-tested for fidelity to the
    ``regime_gate`` worker (which materializes the same ``_macro_quadrant`` into
    ``regime_gate_daily.quadrant``), but NOT called on the backend runtime path
    — the builder/macro route read the quadrant from ``fetch_gate_regime``.

    Growth = SPY ``g_look``-day return sign. Inflation = (TIP − IEF) breakeven
    ``i_look``-day momentum sign. Mapping (verbatim ``main.py:733-739``):
    growth↑ & infl↓ → RECOVERY; growth↑ & infl↑ → EXPANSION;
    growth↓ & infl↑ → SLOWDOWN; growth↓ & infl↓ → CONTRACTION. Returns ``None``
    if any underlying return is unavailable.
    """
    g = _pct_return(spy_desc, g_look)
    tip_r = _pct_return(tip_desc, i_look)
    ief_r = _pct_return(ief_desc, i_look)
    if g is None or tip_r is None or ief_r is None:
        return None
    inflation_score = tip_r - ief_r   # breakeven momentum
    growth_up = g > 0.0
    infl_up = inflation_score > 0.0
    if growth_up and not infl_up:
        quadrant = "RECOVERY"      # growth up, inflation down
    elif growth_up and infl_up:
        quadrant = "EXPANSION"     # growth up, inflation up
    elif (not growth_up) and infl_up:
        quadrant = "SLOWDOWN"      # growth down, inflation up
    else:
        quadrant = "CONTRACTION"   # growth down, inflation down
    return {
        "quadrant": quadrant,
        "growth_state": "up" if growth_up else "down",
        "inflation_state": "up" if infl_up else "down",
        "growth_score": g,
        "inflation_score": inflation_score,
    }


# ── Vol / beta graduated cap vectors + supporting stress / betas ──────────────
def market_stress(spy_closes_desc: list[float], *, window: int = 63) -> float:
    """Continuous market-stress score in [0, 1] from SPY drawdown.

    SPY drawdown from its trailing ``window``-day high, scaled so a 12% drawdown
    is full stress. Newest-first input. Returns 0.0 with ``< window + 1`` points.
    Port of ``_market_stress`` (``main.py:1026-1037``).
    """
    if len(spy_closes_desc) < window + 1:
        return 0.0
    recent = spy_closes_desc[: window + 1]   # newest first
    hi = max(recent)
    now = recent[0]
    dd = (hi - now) / hi if hi > 0 else 0.0
    return min(1.0, max(0.0, dd / 0.12))


def asset_betas(
    asset_returns: dict[str, np.ndarray], spy_returns: np.ndarray
) -> dict[str, float]:
    """Per-asset trailing beta to SPY over the common tail.

    ``cov(r, spy) / var(spy)`` over the overlapping tail; defaults to 1.0 when
    there are fewer than 40 common observations or ``var(spy) <= 0``. Port of
    ``_asset_betas`` (``main.py:998-1014``).
    """
    var = float(np.var(spy_returns))
    out: dict[str, float] = {}
    for ticker, r in asset_returns.items():
        n = min(len(r), len(spy_returns))
        if n >= 40 and var > 0:
            out[ticker] = float(
                np.cov(r[-n:], spy_returns[-n:])[0, 1] / var
            )
        else:
            out[ticker] = 1.0
    return out


def vol_graduated_caps(
    base_cap: float,
    asset_returns_by_index: list[np.ndarray],
    spy_closes_desc: list[float],
    *,
    vg_beta: float = VG_BETA,
) -> np.ndarray:
    """Throttle above-median-vol assets under market stress.

    Port of ``_vol_graduated_caps`` (``main.py:1039-1061``). With zero stress,
    returns ``full(n, base_cap)``. Otherwise per-asset
    ``cap = base_cap * min(1, max(0.02, 1 - vg_beta * stress * excess_vol))``
    where ``excess_vol = max(0, sigma_i / median - 1)`` (only above-median-vol
    assets are cut). Vol uses up to the freshest 42 returns of each series.
    """
    n = len(asset_returns_by_index)
    stress = market_stress(spy_closes_desc)
    if stress <= 0.0:
        return np.full(n, base_cap)
    vols: list[float] = []
    for r in asset_returns_by_index:
        tail = np.asarray(r, dtype=float)[-42:]
        vols.append(float(np.std(tail)) if len(tail) > 5 else 0.0)
    vols_arr = np.array(vols)
    pos = vols_arr[vols_arr > 0]
    med = float(np.median(pos)) if pos.size else 1.0
    caps = np.full(n, base_cap)
    if med > 0:
        for i in range(n):
            excess = max(0.0, vols_arr[i] / med - 1.0)
            caps[i] = base_cap * min(1.0, max(0.02, 1.0 - vg_beta * stress * excess))
    return caps


def beta_graduated_caps(
    base_caps: np.ndarray,
    betas_in_order: list[float],
    *,
    bg_coef: float = BG_COEF,
) -> np.ndarray:
    """Throttle high-beta-to-SPY assets (applied only in RISK_OFF by the caller).

    Port of ``_beta_graduated_caps`` (``main.py:1016-1024``): per-asset
    ``cap = base_caps[i] * min(1, max(0.02, 1 - bg_coef * max(0, beta_i - 0.3)))``.
    Low-beta names (cash / short-govt / gold) are kept.
    """
    caps = np.array(base_caps, dtype=float)
    for i, beta in enumerate(betas_in_order):
        excess = max(0.0, beta - 0.3)
        caps[i] = base_caps[i] * min(1.0, max(0.02, 1.0 - bg_coef * excess))
    return caps


# ── regime_gate_daily reader (decision A: returns growth/inflation/quadrant) ──
@dataclass(frozen=True)
class GateRegimeSnapshot:
    """Latest ``regime_gate_daily`` row (Sprint 1 worker output).

    ``growth_score`` / ``inflation_score`` / ``quadrant`` (decision A) carry the
    worker-materialized growth × inflation clock — the single source of truth the
    builder (Sprint 3) and the macro route (Sprint 4) consume. ``quadrant`` is
    stored lowercase (``recovery|expansion|slowdown|contraction|None``).
    """

    as_of: dt.date
    state: str
    vote_count: int
    trend_vote: bool
    credit_vote: bool
    drawdown_vote: bool
    dwell_days: int
    last_flip: dt.date | None
    growth_score: float | None
    inflation_score: float | None
    quadrant: str | None


_GATE_LATEST_SQL = text("""
    SELECT regime_date, state, vote_count, trend_vote, credit_vote,
           drawdown_vote, dwell_days, growth_score, inflation_score, quadrant
    FROM regime_gate_daily
    ORDER BY regime_date DESC
    LIMIT 1
""")


async def fetch_gate_regime(datalake: AsyncSession) -> GateRegimeSnapshot | None:
    """Read the latest gate state + quadrant from ``regime_gate_daily``.

    Mirrors ``macro_regime.fetch_composite_regime``. Returns ``None`` on an empty
    result, and degrades to ``None`` (try/except) when the relation is absent —
    matching how the composite reader tolerates a missing table. The decision-A
    columns (``growth_score`` / ``inflation_score`` / ``quadrant``) default to
    ``None`` if absent on an older Sprint-1 table.
    """
    try:
        latest = (await datalake.execute(_GATE_LATEST_SQL)).first()
    except Exception:
        return None
    if latest is None:
        return None

    def f(value: Any) -> float | None:
        return float(value) if value is not None else None

    return GateRegimeSnapshot(
        as_of=latest.regime_date,
        state=latest.state,
        vote_count=latest.vote_count,
        trend_vote=latest.trend_vote,
        credit_vote=latest.credit_vote,
        drawdown_vote=latest.drawdown_vote,
        dwell_days=latest.dwell_days,
        last_flip=None,
        growth_score=f(getattr(latest, "growth_score", None)),
        inflation_score=f(getattr(latest, "inflation_score", None)),
        quadrant=getattr(latest, "quadrant", None),
    )
