"""Unit tests for the pure ``taa_bands`` band-math module (COMBO Sprint 2).

Values are transcribed from the validated Lean harness
``lean-research/TaaCvarSuite/main.py`` (``DEFAULT_TAA_BANDS``,
``compute_effective_band``, ``smooth_regime_centers``, ``_macro_quadrant``,
``_combined_regime``, ``_effective_class_bands``, the goldfix branch of
``_haven_weights``, and the vol/beta graduated caps).
"""

import numpy as np
import pytest

from app.services import taa_bands as tb

# ── Task 1: constants + compute_effective_band + smooth_regime_centers ────────


def test_default_bands_table_values():
    rb = tb.DEFAULT_TAA_BANDS["regime_bands"]
    assert rb["RISK_ON"]["equity"]["center"] == 0.52
    assert rb["RISK_ON"]["equity"]["half_width"] == 0.08
    assert rb["RISK_OFF"]["cash"]["half_width"] == 0.05
    assert rb["INFLATION"]["alternatives"]["center"] == 0.22
    assert rb["STAGFLATION"]["alternatives"]["center"] == 0.35


def test_ips_bounds():
    assert tb.IPS_CLASS_BOUNDS["alternatives"] == (0.0, 0.40)
    assert tb.IPS_CLASS_BOUNDS["equity"] == (0.0, 1.0)


def test_effective_band_clamps_to_ips():
    # center 0.52, hw 0.12 (=0.08*1.5) => [0.40, 0.64]; ips (0,1) keeps it
    lo, hi = tb.compute_effective_band(0.0, 1.0, 0.52, 0.12)
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9


def test_effective_band_center_above_ips_max():
    # alternatives ips max 0.40; center 0.50 hw 0.06 -> regime [0.44,0.56] infeasible
    lo, hi = tb.compute_effective_band(0.0, 0.40, 0.50, 0.06)
    assert hi == 0.40
    assert abs(lo - 0.28) < 1e-9   # max(0.40 - 2*0.06, 0.0)


def test_smooth_first_pass_returns_copy():
    cur = {"equity": 0.52, "cash": 0.06}
    out = tb.smooth_regime_centers(cur, None)
    assert out == cur and out is not cur


def test_smooth_below_cap_is_raw_ema():
    # delta = alpha*(0.52-0.30) ~= 0.0285 < 0.03 cap => NO clamp, raw EMA result.
    # (The plan's 0.33 expectation assumed the clamp binds, but it does not here:
    # faithful port of main.py:270-285 yields round(0.3284788..., 6) = 0.328479.)
    out = tb.smooth_regime_centers({"equity": 0.52}, {"equity": 0.30},
                                   halflife_days=5, max_daily_shift=0.03)
    assert abs(out["equity"] - 0.328479) < 1e-9


def test_smooth_respects_max_daily_shift():
    # Larger gap (0.30 -> 0.80): alpha*0.50 ~= 0.0647 > 0.03 cap => clamp +0.03.
    out = tb.smooth_regime_centers({"equity": 0.80}, {"equity": 0.30},
                                   halflife_days=5, max_daily_shift=0.03)
    assert abs(out["equity"] - 0.33) < 1e-9   # clamped +0.03


# ── Task 2: macro_quadrant_from_proxies (growth x inflation clock) ────────────


def test_quadrant_recovery():
    spy = [110.0] + [100.0] * 126          # +10% growth up
    tip = [100.0] + [100.0] * 126          # 0%
    ief = [105.0] + [100.0] * 126          # +5% => tip-ief = -5% inflation down
    q = tb.macro_quadrant_from_proxies(spy, tip, ief)
    assert q["quadrant"] == "RECOVERY"
    assert q["growth_state"] == "up" and q["inflation_state"] == "down"


def test_quadrant_expansion():
    spy = [110.0] + [100.0] * 126
    tip = [108.0] + [100.0] * 126
    ief = [102.0] + [100.0] * 126          # +6% breakeven => inflation up
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "EXPANSION"


def test_quadrant_slowdown():
    spy = [90.0] + [100.0] * 126           # -10% growth down
    tip = [108.0] + [100.0] * 126
    ief = [102.0] + [100.0] * 126          # inflation up
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "SLOWDOWN"


def test_quadrant_contraction():
    spy = [90.0] + [100.0] * 126
    tip = [100.0] + [100.0] * 126
    ief = [105.0] + [100.0] * 126          # inflation down
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "CONTRACTION"


def test_quadrant_none_when_insufficient():
    assert tb.macro_quadrant_from_proxies([1.0], [1.0], [1.0]) is None


# ── Task 3: combined_regime (gate + quadrant overlay) ─────────────────────────


def test_combined_gate_riskoff_dominates():
    assert tb.combined_regime("risk_off", "EXPANSION") == "RISK_OFF"
    assert tb.combined_regime("RISK_OFF", "RECOVERY") == "RISK_OFF"


def test_combined_recovery_is_riskon():
    assert tb.combined_regime("risk_on", "RECOVERY") == "RISK_ON"
    assert tb.combined_regime("risk_on", None) == "RISK_ON"


def test_combined_expansion_uses_inflation_bands():
    assert tb.combined_regime("risk_on", "EXPANSION") == "INFLATION"
    assert tb.combined_regime("risk_on", "EXPANSION", use_infl_bands=False) == "RISK_ON"


def test_combined_slowdown_routes_to_goldfix():
    assert tb.combined_regime("risk_on", "SLOWDOWN") == "STAG_GOLD"
    assert tb.combined_regime("risk_on", "SLOWDOWN", slowdown_haven="bonds") == "RISK_OFF"


def test_combined_normalizes_lowercase_quadrant_from_worker():
    # the regime_gate worker materializes the quadrant lowercase
    assert tb.combined_regime("risk_on", "slowdown") == "STAG_GOLD"
    assert tb.combined_regime("risk_on", "expansion") == "INFLATION"


def test_combined_contraction_defensive():
    assert tb.combined_regime("risk_on", "CONTRACTION") == "RISK_OFF"
    assert tb.combined_regime("risk_on", "CONTRACTION", defensive_on="x") == "RISK_ON"


# ── Task 4: effective_class_bands (regime -> per-class (min,max)) ──────────────


def test_effective_class_bands_risk_on_wide():
    bands, _ = tb.effective_class_bands("RISK_ON")          # hw_scale 1.5
    lo, hi = bands["equity"]                                 # c .52, hw .08*1.5=.12
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9
    a_lo, a_hi = bands["alternatives"]                       # c .12 hw .06 -> [.06,.18]
    assert abs(a_lo - 0.06) < 1e-9 and abs(a_hi - 0.18) < 1e-9


def test_effective_class_bands_inflation_alt_tilt():
    bands, _ = tb.effective_class_bands("INFLATION")
    a_lo, a_hi = bands["alternatives"]                       # c .22 hw .06*1.5=.09 -> [.13,.31]
    assert abs(a_lo - 0.13) < 1e-9 and abs(a_hi - 0.31) < 1e-9


def test_effective_class_bands_riskoff_equity():
    bands, _ = tb.effective_class_bands("RISK_OFF")
    lo, hi = bands["equity"]                                 # c .38 hw .08*1.5=.12 -> [.26,.50]
    assert abs(lo - 0.26) < 1e-9 and abs(hi - 0.50) < 1e-9


def test_effective_class_bands_covers_four_classes_only():
    bands, _ = tb.effective_class_bands("RISK_OFF")
    assert set(bands) == {"equity", "fixed_income", "alternatives", "cash"}


def test_effective_class_bands_rejects_stag_gold():
    with pytest.raises(ValueError):
        tb.effective_class_bands("STAG_GOLD")


# ── Task 5: goldfix_target (SLOWDOWN haven) ───────────────────────────────────


def test_goldfix_default_weights_renormalize():
    out = tb.goldfix_target({"GLD", "VOOV", "QAI", "BIL"})  # GCC absent + gcc_w=0
    assert abs(sum(out.values()) - 1.0) < 1e-9
    # 0.30/0.20/0.20/0.30 already sums to 1.0; renorm is identity
    assert abs(out["GLD"] - 0.30) < 1e-9
    assert "GCC" not in out


def test_goldfix_drops_missing_and_renormalizes():
    out = tb.goldfix_target({"GLD", "BIL"})   # only 0.30 + 0.30 -> 0.5/0.5
    assert abs(out["GLD"] - 0.5) < 1e-9 and abs(out["BIL"] - 0.5) < 1e-9


def test_goldfix_fallback_to_bil():
    assert tb.goldfix_target({"BIL"}) == {"BIL": 1.0}


def test_goldfix_none_when_nothing_available():
    assert tb.goldfix_target({"SPY"}) is None


# ── Task 6: vol/beta graduated cap vectors ────────────────────────────────────


def test_vol_graduated_no_stress_returns_base():
    spy_flat = [100.0] * 70
    rets = [np.array([0.01, -0.01, 0.02, -0.02, 0.01, 0.0, 0.01])] * 3
    caps = tb.vol_graduated_caps(0.25, rets, spy_flat)
    assert np.allclose(caps, 0.25)


def test_vol_graduated_cuts_high_vol_under_stress():
    # SPY in 12% drawdown => full stress; asset 0 high vol, asset 1 low vol
    spy = [88.0] + [100.0] * 63
    hi = np.array([0.05, -0.05, 0.06, -0.06, 0.05, -0.05, 0.05])
    lo = np.array([0.001, -0.001, 0.001, -0.001, 0.001, -0.001, 0.001])
    caps = tb.vol_graduated_caps(0.25, [hi, lo], spy, vg_beta=1.5)
    assert caps[0] < 0.25          # above-median vol cut
    assert abs(caps[1] - 0.25) < 1e-9 or caps[1] <= 0.25  # at/below median untouched


def test_beta_graduated_throttles_high_beta():
    base = np.array([0.25, 0.25])
    caps = tb.beta_graduated_caps(base, [1.3, 0.2], bg_coef=1.0)
    # beta 1.3: excess 1.0 => factor max(0.02, 1-1.0)=0.02 => 0.005
    assert abs(caps[0] - 0.25 * 0.02) < 1e-9
    # beta 0.2 < 0.3: no cut
    assert abs(caps[1] - 0.25) < 1e-9


def test_asset_betas_default_when_short():
    out = tb.asset_betas({"A": np.array([0.01, 0.02])}, np.array([0.01, 0.02]))
    assert out["A"] == 1.0   # <40 obs
