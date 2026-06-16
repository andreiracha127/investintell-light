"""Black-Litterman layer (F8.4) — the ONLY place expected returns exist.

Pipeline (validated numerically in
docs/research/2026-06-11-f8-optimizer-black-litterman.md):

    Σ (Ledoit-Wolf, annualized) → w_mkt (real AUM) → π = δ·Σ·w_mkt
    → views (P, Q) + Ω (Idzorek-style confidence scaling)
    → posterior (μ_BL, Σ_BL) via the master formula
    → either re-centered scenarios for min-CVaR (product default)
      or BL max-utility weights (optional ``bl_utility`` objective).

Gate G5 note: ``historical_mean_ann`` (sample mean of daily returns) lives
HERE, and is used exclusively to re-center scenarios around μ_BL — never as an
optimization objective on its own.
"""

from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from app.optimizer.engine import (
    TRADING_DAYS,
    OptimizerError,
    _check_constraint_params,
    _finalize,
    _validate_sigma,
    base_constraints,
)

DEFAULT_DELTA = 2.5
DEFAULT_TAU = 0.05

# Ω scaling factor at confidence = 1 (see omega_idzorek): a strictly positive
# epsilon keeps Ω invertible while making the view ~certain.
_FULL_CONFIDENCE_EPS = 1e-6


@dataclass(frozen=True)
class AbsoluteView:
    """'Asset i returns q per year' — indices refer to the problem universe."""

    asset: int
    q: float
    confidence: float


@dataclass(frozen=True)
class RelativeView:
    """'Asset `long` outperforms asset `short` by q per year'."""

    long: int
    short: int
    q: float
    confidence: float


View = AbsoluteView | RelativeView


def market_weights(aums: list[float | None], labels: list[str]) -> np.ndarray:
    """Normalize the universe's AUM into market weights.

    Fail-loud (dispatch F8.4): assets with unknown AUM raise a ValueError
    listing them — the caller decides whether to exclude assets, we never
    silently fall back to equal weight.
    """
    if len(aums) != len(labels):
        raise ValueError(f"aums ({len(aums)}) and labels ({len(labels)}) length mismatch")
    if not aums:
        raise ValueError("market_weights requires at least one asset")
    missing = [
        label for label, aum in zip(labels, aums, strict=True) if aum is None or aum <= 0
    ]
    if missing:
        raise ValueError(
            "market weights require a known positive AUM for every asset; missing/invalid "
            f"for: {', '.join(missing)}"
        )
    arr = np.asarray([float(a) for a in aums if a is not None], dtype=float)
    return np.asarray(arr / arr.sum())


def equilibrium(
    sigma_ann: np.ndarray, w_mkt: np.ndarray, delta: float = DEFAULT_DELTA
) -> np.ndarray:
    """Reverse optimization: π = δ·Σ·w_mkt (annualized implied excess returns)."""
    sigma_ann = _validate_sigma(sigma_ann, "equilibrium")
    w_mkt = np.asarray(w_mkt, dtype=float).ravel()
    if w_mkt.shape[0] != sigma_ann.shape[0]:
        raise ValueError(
            f"w_mkt has {w_mkt.shape[0]} assets but sigma is {sigma_ann.shape[0]}×"
            f"{sigma_ann.shape[1]}"
        )
    if delta <= 0:
        raise ValueError(f"delta must be > 0, got {delta}")
    return np.asarray(delta * sigma_ann @ w_mkt)


def build_view_matrices(views: list[View], n_assets: int) -> tuple[np.ndarray, np.ndarray]:
    """Assemble the k×n pick matrix P and the k-vector Q from typed views.

    Validates indices and the rank of P: linearly dependent views make Ω/the
    posterior ill-defined and are rejected fail-loud.
    """
    if not views:
        raise ValueError("at least one view is required")
    k = len(views)
    p = np.zeros((k, n_assets), dtype=float)
    q = np.zeros(k, dtype=float)
    for i, view in enumerate(views):
        if isinstance(view, AbsoluteView):
            indices = [view.asset]
        else:
            if view.long == view.short:
                raise ValueError(f"view {i}: relative view long and short are the same asset")
            indices = [view.long, view.short]
        for idx in indices:
            if not 0 <= idx < n_assets:
                raise ValueError(f"view {i}: asset index {idx} out of range (n={n_assets})")
        if isinstance(view, AbsoluteView):
            p[i, view.asset] = 1.0
        else:
            p[i, view.long] = 1.0
            p[i, view.short] = -1.0
        q[i] = float(view.q)
    if np.linalg.matrix_rank(p) < k:
        raise ValueError(
            "views linearmente dependentes: a matriz P tem posto deficiente — "
            "remova ou combine views redundantes"
        )
    return p, q


def omega_idzorek(
    p: np.ndarray,
    sigma_ann: np.ndarray,
    confidences: list[float],
    tau: float = DEFAULT_TAU,
) -> np.ndarray:
    """View-uncertainty matrix Ω with Idzorek-style confidence scaling.

    Base uncertainty (He–Litterman): ω_base,i = [P·τΣ·Pᵀ]ᵢᵢ. Each view's
    confidence cᵢ ∈ (0, 1] scales it as

        ωᵢ = ω_base,i · (1 − cᵢ)/cᵢ        (cᵢ < 1)
        ωᵢ = ω_base,i · ε  (ε = 1e-6)      (cᵢ = 1, keeps Ω invertible)

    Monotonic by construction: cᵢ → 0 ⇒ ωᵢ → ∞ (view ignored);
    higher confidence ⇒ smaller ωᵢ ⇒ stronger tilt toward the view.
    """
    sigma_ann = _validate_sigma(sigma_ann, "omega_idzorek")
    p = np.asarray(p, dtype=float)
    if p.ndim != 2 or p.shape[1] != sigma_ann.shape[0]:
        raise ValueError(f"P shape {p.shape} incompatible with sigma {sigma_ann.shape}")
    if len(confidences) != p.shape[0]:
        raise ValueError(
            f"{len(confidences)} confidences for {p.shape[0]} views — must match"
        )
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    base = np.diag(p @ (tau * sigma_ann) @ p.T).copy()
    if (base <= 0).any():
        raise ValueError("Ω base diagonal has non-positive entries — degenerate view/sigma")
    omega = np.empty_like(base)
    for i, c in enumerate(confidences):
        if not 0 < c <= 1:
            raise ValueError(f"view {i}: confidence must be in (0, 1], got {c}")
        factor = _FULL_CONFIDENCE_EPS if c >= 1.0 else (1.0 - c) / c
        omega[i] = base[i] * factor
    return np.diag(omega)


def posterior(
    sigma_ann: np.ndarray,
    pi: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    omega: np.ndarray,
    tau: float = DEFAULT_TAU,
) -> tuple[np.ndarray, np.ndarray]:
    """Black-Litterman master formula.

        M     = inv( inv(τΣ) + Pᵀ·Ω⁻¹·P )
        μ_BL  = M · ( inv(τΣ)·π + Pᵀ·Ω⁻¹·Q )
        Σ_BL  = Σ + M

    All inputs annualized. Raises on singular τΣ or Ω (fail-loud → 422).
    """
    sigma_ann = _validate_sigma(sigma_ann, "posterior")
    pi = np.asarray(pi, dtype=float).ravel()
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float).ravel()
    omega = np.asarray(omega, dtype=float)
    n = sigma_ann.shape[0]
    if pi.shape != (n,):
        raise ValueError(f"pi has shape {pi.shape}, expected ({n},)")
    if p.shape != (q.shape[0], n):
        raise ValueError(f"P shape {p.shape} inconsistent with Q ({q.shape[0]}) / n ({n})")
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    try:
        tau_sigma_inv = np.linalg.inv(tau * sigma_ann)
        omega_inv = np.linalg.inv(omega)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"singular matrix in BL posterior (τΣ or Ω): {exc}") from exc
    m = np.linalg.inv(tau_sigma_inv + p.T @ omega_inv @ p)
    mu_bl: np.ndarray = m @ (tau_sigma_inv @ pi + p.T @ omega_inv @ q)
    sigma_bl: np.ndarray = sigma_ann + m
    return mu_bl, (sigma_bl + sigma_bl.T) / 2.0


# Per-entry Ω regularization floor (legacy REG_OMEGA_EPS_FACTOR,
# black_litterman_service.py:56): a confidence=1 view drives Ω_ii -> 0; we floor
# each diagonal entry relative to its own magnitude so a near-certain view stays
# dominant without making Ω singular.
_REG_OMEGA_EPS_FACTOR = 1e-8


def posterior_woodbury(
    sigma_ann: np.ndarray,
    pi: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    omega: np.ndarray,
    tau: float = DEFAULT_TAU,
) -> np.ndarray:
    """BL posterior mean via the Woodbury data-update form (full Ω supported).

    Ported from quant_engine/black_litterman_service.py:239-253:

        μ_BL = π + τΣ·Pᵀ · (P·τΣ·Pᵀ + Ω)⁻¹ · (Q − P·π)

    Never inverts τΣ — only the strictly-PD K×K view-space matrix
    (P·τΣ·Pᵀ + Ω_reg). A zero-variance asset transmits no information (its row
    of τΣ·Pᵀ is zero) instead of producing a singular τΣ. Accepts a FULL
    (non-diagonal) Ω; a per-entry diagonal floor keeps the solve stable even
    for confidence≈1 views.

    Returns the posterior MEAN only (the classic :func:`posterior` returns mean
    and Σ_BL; callers needing Σ_BL keep using it). All inputs annualized.

    Raises:
        ValueError: shape mismatch, non-finite inputs, non-symmetric/non-PSD Ω,
            tau ≤ 0, or a singular view-space matrix.
    """
    sigma_ann = _validate_sigma(sigma_ann, "posterior_woodbury")
    pi = np.asarray(pi, dtype=float).ravel()
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float).ravel()
    omega = np.asarray(omega, dtype=float)
    n = sigma_ann.shape[0]
    if pi.shape != (n,):
        raise ValueError(f"pi has shape {pi.shape}, expected ({n},)")
    if p.ndim != 2 or p.shape[1] != n:
        raise ValueError(f"P shape {p.shape} inconsistent with n ({n})")
    k = p.shape[0]
    if q.shape != (k,):
        raise ValueError(f"Q shape {q.shape} inconsistent with P rows ({k})")
    if omega.shape != (k, k):
        raise ValueError(f"Omega shape {omega.shape} inconsistent with P rows ({k})")
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    if not (np.isfinite(pi).all() and np.isfinite(p).all()
            and np.isfinite(q).all() and np.isfinite(omega).all()):
        raise ValueError("posterior_woodbury: non-finite input")
    if not np.allclose(omega, omega.T, atol=1e-12):
        raise ValueError("Omega must be symmetric")
    if float(np.linalg.eigvalsh(omega).min()) < -1e-10:
        raise ValueError("Omega is not PSD (negative eigenvalue)")

    # Per-entry diagonal regularization (legacy lines 218-237).
    omega_diag = np.clip(np.diag(omega), 0.0, None)
    positive = omega_diag[omega_diag > 0.0]
    if positive.size == 0:
        eps_vec = np.full(k, 1e-12)
    else:
        floor_for_zero = _REG_OMEGA_EPS_FACTOR * float(positive.min())
        eps_vec = np.where(
            omega_diag > 0.0, _REG_OMEGA_EPS_FACTOR * omega_diag, floor_for_zero
        )
    omega_reg = omega + np.diag(eps_vec)

    tau_sigma = tau * sigma_ann                       # (N, N)
    tau_sigma_pt = tau_sigma @ p.T                    # (N, K)
    view_space = p @ tau_sigma_pt + omega_reg         # (K, K) strictly PD
    innovation = q - p @ pi                           # (K,)
    try:
        mu_post = pi + tau_sigma_pt @ np.linalg.solve(view_space, innovation)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            f"posterior_woodbury: singular view-space matrix (P·τΣ·Pᵀ + Ω): {exc}"
        ) from exc
    if not np.all(np.isfinite(mu_post)):
        raise ValueError("posterior_woodbury produced non-finite output")
    return np.asarray(mu_post, dtype=float)


# He-Litterman (1999) consistency threshold: a view Q more than this many
# predictive sigmas from its prior-implied value P*pi is "fighting the prior".
_HE_LITTERMAN_SIGMA = 3.0


def view_consistency_he_litterman(
    p: np.ndarray,
    q: np.ndarray,
    pi: np.ndarray,
    omega: np.ndarray,
    sigma_ann: np.ndarray,
    tau: float = DEFAULT_TAU,
) -> dict[str, object]:
    """He-Litterman (1999) view-vs-prior consistency check.

    For each view, the prior-implied value is P*pi and the predictive
    dispersion of (Q - P*pi) is sqrt(diag(P*(tau*Sigma)*P' + Omega)). A view
    whose |Q - P*pi| exceeds ``_HE_LITTERMAN_SIGMA`` times that dispersion is
    the textbook "views fighting the equilibrium" red flag. Returns a
    structured summary (never raises on a degenerate sigma -> z=0 there).
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float).ravel()
    pi = np.asarray(pi, dtype=float).ravel()
    omega = np.asarray(omega, dtype=float)
    sigma_ann = np.asarray(sigma_ann, dtype=float)
    prior_view = p @ pi                                   # (K,)
    view_cov = p @ (tau * sigma_ann) @ p.T + omega        # (K, K) predictive cov
    view_sigma = np.sqrt(np.maximum(np.diag(view_cov), 0.0))
    residual = np.abs(q - prior_view)
    z = residual / np.where(view_sigma > 0, view_sigma, 1.0)
    inconsistent = z > _HE_LITTERMAN_SIGMA
    return {
        "inconsistent": bool(inconsistent.any()),
        "n_flagged": int(inconsistent.sum()),
        "max_z": round(float(z.max()) if z.size else 0.0, 4),
        "threshold_sigma": _HE_LITTERMAN_SIGMA,
    }


def historical_mean_ann(scenarios_daily: np.ndarray) -> np.ndarray:
    """Annualized sample mean of daily scenarios — BL re-centering ONLY.

    Gate G5: this is the single sanctioned historical-mean estimator in the
    optimizer package, and its sole consumer is ``recenter_scenarios`` (the
    shift μ_BL − μ_hist). It must never feed an optimization objective.
    """
    scenarios_daily = np.asarray(scenarios_daily, dtype=float)
    if scenarios_daily.ndim != 2:
        raise ValueError(f"scenarios must be T×n, got ndim={scenarios_daily.ndim}")
    return np.asarray(scenarios_daily.mean(axis=0) * TRADING_DAYS)


def recenter_scenarios(
    scenarios_daily: np.ndarray,
    mu_hist_ann: np.ndarray,
    mu_bl_ann: np.ndarray,
) -> np.ndarray:
    """Shift daily scenarios by (μ_BL − μ_hist)/252 (per asset).

    Preserves the historical co-movement/tail shape while moving the center of
    the distribution to the BL posterior — the product-default way views enter
    the min-CVaR objective.
    """
    scenarios_daily = np.asarray(scenarios_daily, dtype=float)
    mu_hist_ann = np.asarray(mu_hist_ann, dtype=float).ravel()
    mu_bl_ann = np.asarray(mu_bl_ann, dtype=float).ravel()
    if scenarios_daily.ndim != 2:
        raise ValueError(f"scenarios must be T×n, got ndim={scenarios_daily.ndim}")
    n = scenarios_daily.shape[1]
    if mu_hist_ann.shape != (n,) or mu_bl_ann.shape != (n,):
        raise ValueError(
            f"mu vectors must have shape ({n},), got {mu_hist_ann.shape} / {mu_bl_ann.shape}"
        )
    shift_daily = (mu_bl_ann - mu_hist_ann) / TRADING_DAYS
    return np.asarray(scenarios_daily + shift_daily[np.newaxis, :])


def solve_bl_utility(
    mu_ann: np.ndarray,
    sigma_ann: np.ndarray,
    delta: float = DEFAULT_DELTA,
    cap: float | None = None,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Max-utility weights: max μᵀw − (δ/2)·wᵀΣw, long-only, sum=1.

    Lives here (not in ``engine``) because it is the one objective that
    consumes expected returns — by contract μ is the BL posterior (or π for
    the zero-views sanity case, where the unconstrained optimum recovers
    w_mkt exactly).
    """
    sigma_ann = _validate_sigma(sigma_ann, "bl_utility")
    mu_arr = np.asarray(mu_ann, dtype=float).ravel()
    n = sigma_ann.shape[0]
    if mu_arr.shape != (n,):
        raise OptimizerError(f"bl_utility: mu has shape {mu_arr.shape}, expected ({n},)")
    if delta <= 0:
        raise OptimizerError(f"bl_utility: delta must be > 0, got {delta}")
    _check_constraint_params(n, cap, min_weight)
    w = cp.Variable(n)
    objective = cp.Maximize(mu_arr @ w - (delta / 2.0) * cp.quad_form(w, cp.psd_wrap(sigma_ann)))
    problem = cp.Problem(objective, base_constraints(w, cap, min_weight))
    return _finalize(problem, w, "bl_utility")


def _kappa_from_chi2(
    confidence: float, n: int, uncertainty_level: float | None
) -> float:
    """Ellipsoid radius κ = √(chi2.ppf(confidence, df=n)), optionally scaled.

    The (1-confidence) ellipsoidal confidence region of a μ estimate has
    half-width √(χ²_{n}(confidence)) in the Σ-metric (legacy
    optimizer_service lines 1471-1472). ``uncertainty_level`` (>0) linearly
    rescales the radius; None ⇒ 1.0.
    """
    from scipy.stats import chi2

    if not 0 < confidence < 1:
        raise OptimizerError(f"bl_robust: confidence must be in (0, 1), got {confidence}")
    if n < 1:
        raise OptimizerError("bl_robust: n must be >= 1")
    kappa = float(np.sqrt(chi2.ppf(confidence, df=n)))
    if uncertainty_level is not None:
        if uncertainty_level <= 0:
            raise OptimizerError(
                f"bl_robust: uncertainty_level must be > 0, got {uncertainty_level}"
            )
        kappa *= float(uncertainty_level)
    return kappa


def solve_bl_robust(
    mu_ann: np.ndarray,
    sigma_ann: np.ndarray,
    cap: float | None = None,
    min_weight: float | None = None,
    confidence: float = 0.95,
    uncertainty_level: float | None = None,
) -> tuple[np.ndarray, str]:
    """Robust max-return under ellipsoidal μ-uncertainty (SOCP).

        max  μᵀw − κ·‖Lᵀw‖₂      s.t. long-only, sum(w)=1, optional cap/min

    where L = cholesky(Σ) and κ = √(chi2.ppf(confidence, df=n)) scaled by
    ``uncertainty_level``. Gate G5: μ is the BL posterior (or π) — never a
    sample mean. Ported from legacy optimizer_service Phase-2 robust RU.

    Infeasibility / non-optimal solve raise ``OptimizerError`` (→ 422).
    """
    sigma_ann = _validate_sigma(sigma_ann, "bl_robust")
    mu_arr = np.asarray(mu_ann, dtype=float).ravel()
    n = sigma_ann.shape[0]
    if mu_arr.shape != (n,):
        raise OptimizerError(f"bl_robust: mu has shape {mu_arr.shape}, expected ({n},)")
    _check_constraint_params(n, cap, min_weight)

    try:
        chol = np.linalg.cholesky(sigma_ann)
    except np.linalg.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(sigma_ann)
        floored = np.maximum(eigvals, 1e-12)
        chol = eigvecs @ np.diag(np.sqrt(floored))

    kappa = _kappa_from_chi2(confidence, n, uncertainty_level)
    w = cp.Variable(n)
    objective = cp.Maximize(mu_arr @ w - kappa * cp.norm(chol.T @ w, 2))
    problem = cp.Problem(objective, base_constraints(w, cap, min_weight))
    return _finalize(problem, w, "bl_robust", cap=cap, min_weight=min_weight)


def solve_bl_vol_target(
    mu_ann: np.ndarray,
    sigma_ann: np.ndarray,
    vol_target: float,
    cap: float | None = None,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Max BL return subject to an annualized volatility cap (SOCP).

        max μᵀw   s.t.  ‖Lᵀw‖₂ ≤ vol_target, long-only, sum(w)=1, cap/min

    where L = cholesky(Σ). μ-consuming ⇒ lives with BL (gate G5). When the
    target is below the achievable floor volatility (min-variance portfolio),
    the cone is infeasible and the failure is reported loud with that floor.
    Ported from legacy optimizer_service vol_target phase (line 1135).
    """
    sigma_ann = _validate_sigma(sigma_ann, "bl_vol_target")
    mu_arr = np.asarray(mu_ann, dtype=float).ravel()
    n = sigma_ann.shape[0]
    if mu_arr.shape != (n,):
        raise OptimizerError(f"bl_vol_target: mu has shape {mu_arr.shape}, expected ({n},)")
    if vol_target <= 0:
        raise OptimizerError(f"bl_vol_target: vol_target must be > 0, got {vol_target}")
    _check_constraint_params(n, cap, min_weight)

    try:
        chol = np.linalg.cholesky(sigma_ann)
    except np.linalg.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(sigma_ann)
        floored = np.maximum(eigvals, 1e-12)
        chol = eigvecs @ np.diag(np.sqrt(floored))

    w = cp.Variable(n)
    cons = base_constraints(w, cap, min_weight)
    cons.append(cp.norm(chol.T @ w, 2) <= vol_target)
    problem = cp.Problem(cp.Maximize(mu_arr @ w), cons)
    try:
        return _finalize(problem, w, "bl_vol_target", cap=cap, min_weight=min_weight)
    except OptimizerError as exc:
        # Surface the achievable floor when the cap is the binding cause.
        floor_w = cp.Variable(n)
        floor_prob = cp.Problem(
            cp.Minimize(cp.quad_form(floor_w, cp.psd_wrap(sigma_ann))),
            base_constraints(floor_w, cap, min_weight),
        )
        try:
            floor_prob.solve()
        except cp.error.SolverError:  # pragma: no cover - solver-dependent
            raise exc
        if floor_w.value is not None and str(floor_prob.status) == cp.OPTIMAL:
            floor_vol = float(np.sqrt(floor_w.value @ sigma_ann @ floor_w.value))
            if floor_vol > vol_target + 1e-6:
                raise OptimizerError(
                    f"bl_vol_target infeasible: target vol {vol_target} is below the "
                    f"achievable floor {floor_vol:.6f} under these constraints — "
                    "raise the target or relax the cap"
                ) from exc
        raise exc
