"""Pure optimization engine (F8.3) — numpy/cvxpy, no I/O.

Objectives: equal-weight, min-vol, ERC (Spinu convex form), max-diversification,
min-CVaR (Rockafellar–Uryasev on historical scenarios — the product default).

μ-free guard (gate G5): NO function in this module accepts or estimates a mean
of historical returns as an objective input. The single exception is the
optional return floor of ``solve_min_cvar``, which requires an EXPLICIT ``mu``
vector — by contract that vector comes only from the Black-Litterman posterior
(``app.optimizer.black_litterman``), never from a sample mean.

Constraint contract (all solvers): long-only, sum(w) = 1, optional per-asset
cap (default 0.25) and optional per-asset minimum weight. ``cap=None`` disables
the cap (used by analytic gate tests).

Fail-loud: any solver status other than ``optimal`` raises
``OptimizerError`` — never a silently degraded answer.
"""

from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from app.analytics import rmt

TRADING_DAYS = 252

DEFAULT_CAP = 0.25
DEFAULT_CVAR_ALPHA = 0.95

_WEIGHT_ATOL = 1e-6

# CLARABEL is cvxpy's conic default for these QPs/SOCPs; SCS is the robust
# fallback (handles ill-conditioned cones the default may reject). Both are
# confirmed in cp.installed_solvers() (1.8.1). cp.CLARABEL/cp.SCS are the
# string constants "CLARABEL"/"SCS".
_SOLVER_LADDER = (cp.CLARABEL, cp.SCS)


@dataclass(frozen=True)
class SolveTelemetry:
    """Observability for a single engine solve."""

    solver: str
    status: str
    used_fallback: bool
    realized_sum: float
    realized_max_weight: float
    n_assets: int


class OptimizerError(ValueError):
    """Solver failed / problem infeasible / invalid inputs. Mapped to 422."""


def compute_regime_adjusted_limit(base_limit: float, regime_multiplier: float) -> float:
    """Scale a base CVaR loss limit by a regime multiplier.

    ``base_limit`` is a POSITIVE loss magnitude (decimal fraction). A
    ``regime_multiplier`` < 1 tightens the limit under stress (legacy intent:
    in a detected stress regime the institutional CVaR budget shrinks); > 1
    loosens it in calm regimes. The multiplier is supplied by the caller from
    the regime detector — this function performs no estimation (gate G5).

    Raises:
        OptimizerError: if ``base_limit`` or ``regime_multiplier`` is not > 0.
    """
    if not base_limit > 0:
        raise OptimizerError(
            f"base_limit must be > 0 (loss magnitude), got {base_limit}"
        )
    if not regime_multiplier > 0:
        raise OptimizerError(
            f"regime_multiplier must be > 0, got {regime_multiplier}"
        )
    return base_limit * regime_multiplier


def sigma_ledoit_wolf(returns: np.ndarray) -> np.ndarray:
    """Annualized (×252) Ledoit-Wolf shrunk covariance of daily returns.

    ``returns`` is T×n (rows = days, columns = assets). Delegates to
    ``sklearn.covariance.LedoitWolf`` — the reference implementation the G4
    gate compares against (identical by construction, atol 1e-10).
    """
    from sklearn.covariance import LedoitWolf

    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise OptimizerError(f"returns must be a T×n matrix, got ndim={returns.ndim}")
    t, n = returns.shape
    if t < 2 or n < 1:
        raise OptimizerError(f"returns matrix too small for covariance: shape={returns.shape}")
    if not np.isfinite(returns).all():
        raise OptimizerError("returns matrix contains NaN/inf — refusing to estimate covariance")
    lw = LedoitWolf().fit(returns)
    sigma: np.ndarray = np.asarray(lw.covariance_, dtype=float) * TRADING_DAYS
    # Symmetrize (numerical hygiene for cvxpy's PSD checks).
    return np.asarray((sigma + sigma.T) / 2.0)


RMT_Q_THRESHOLD = 0.5  # q = N/T above which the RMT denoise path activates


def sigma_robust(
    returns: np.ndarray, *, q_threshold: float = RMT_Q_THRESHOLD
) -> np.ndarray:
    """Annualized (×252) covariance, method chosen by q = N/T.

    When ``q = N/T > q_threshold`` (a large universe relative to its history)
    the sample correlation is cleaned with the Tier-3 RMT pipeline —
    constant-correlation Ledoit-Wolf shrinkage → Marchenko-Pastur denoise —
    then rescaled by the per-asset volatilities to a covariance. Otherwise the
    plain ``sigma_ledoit_wolf`` is used. BOTH paths end in ``repair_psd`` so the
    result is PSD and well-conditioned. The RMT branch falls back deterministically
    to Ledoit-Wolf if the denoise raises (fail-closed only on an unusable matrix,
    via ``repair_psd``). The ``solve_*`` interfaces are unchanged.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise OptimizerError(f"returns must be a T×n matrix, got ndim={arr.ndim}")
    t, n = arr.shape
    if t < 2 or n < 1:
        raise OptimizerError(
            f"returns matrix too small for covariance: shape={arr.shape}"
        )
    if not np.isfinite(arr).all():
        raise OptimizerError(
            "returns matrix contains NaN/inf — refusing to estimate covariance"
        )

    q = n / t
    if n < 2 or q <= q_threshold:
        return repair_psd(sigma_ledoit_wolf(arr))
    try:
        cov_shrunk, _delta = rmt.ledoit_wolf_constant_correlation(arr)
        std = np.sqrt(np.maximum(np.diag(cov_shrunk), 1e-20))
        corr = cov_shrunk / np.outer(std, std)
        np.fill_diagonal(corr, 1.0)
        corr_denoised = rmt.marchenko_pastur_denoise(corr, q)
        # Re-attach the (annualized) per-asset variances to the denoised corr.
        var_ann = std**2 * TRADING_DAYS
        std_ann = np.sqrt(var_ann)
        cov_ann = corr_denoised * np.outer(std_ann, std_ann)
        return repair_psd(cov_ann)
    except ValueError:
        # Deterministic fallback: RMT denoise could not produce a usable matrix.
        return repair_psd(sigma_ledoit_wolf(arr))


def _check_constraint_params(n: int, cap: float | None, min_weight: float | None) -> None:
    if n < 1:
        raise OptimizerError("at least one asset is required")
    if cap is not None:
        if not 0 < cap <= 1:
            raise OptimizerError(f"cap must be in (0, 1], got {cap}")
        if cap * n < 1 - 1e-12:
            raise OptimizerError(
                f"infeasible constraints: cap {cap} × {n} assets < 1 — "
                "raise the cap or add assets"
            )
    if min_weight is not None:
        if min_weight < 0:
            raise OptimizerError(f"min_weight must be >= 0, got {min_weight}")
        if min_weight * n > 1 + 1e-12:
            raise OptimizerError(
                f"infeasible constraints: min_weight {min_weight} × {n} assets > 1"
            )
        if cap is not None and min_weight > cap:
            raise OptimizerError(f"min_weight {min_weight} exceeds cap {cap}")


def base_constraints(
    w: cp.Variable, cap: float | None, min_weight: float | None
) -> list[cp.Constraint]:
    """Shared constraint block: long-only, sum=1, optional cap / min weight."""
    cons: list[cp.Constraint] = [w >= 0, cp.sum(w) == 1]
    if cap is not None:
        cons.append(w <= cap)
    if min_weight is not None:
        cons.append(w >= min_weight)
    return cons


@dataclass(frozen=True)
class BlockBudget:
    """Group-budget constraint: Σ wᵢ over ``indices`` must lie in [lo, hi].

    ``indices`` are 0-based asset columns (e.g. all funds whose
    ``Fund.asset_class == 'equity'``). ``lo``/``hi`` are decimal fractions of
    the fully-invested portfolio (0.30 = 30%). Convex (linear) by construction,
    so it composes with every objective in this module.
    """

    indices: list[int]
    lo: float
    hi: float


@dataclass(frozen=True)
class BoundsBundle:
    """Optional advanced-constraint bundle for the CVaR solvers.

    When passed to a solver, it REPLACES the scalar (cap, min_weight) block
    with ``bounds_constraints`` — per-asset bound vectors plus block budgets.
    """

    cap_vec: np.ndarray | None = None
    min_vec: np.ndarray | None = None
    blocks: list[BlockBudget] | None = None


def _check_bound_vectors(
    n: int, cap_vec: np.ndarray | None, min_vec: np.ndarray | None
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Validate per-asset cap/min vectors; return them as float ndarrays.

    Element-wise analogue of ``_check_constraint_params``: each cap ∈ (0, 1],
    each min ≥ 0, min ≤ cap, Σ caps ≥ 1 (else sum(w)=1 is unreachable),
    Σ mins ≤ 1. All failures are fail-loud ``OptimizerError``.
    """
    cap_arr = None
    min_arr = None
    if cap_vec is not None:
        cap_arr = np.asarray(cap_vec, dtype=float).ravel()
        if cap_arr.shape != (n,):
            raise OptimizerError(f"cap_vec has shape {cap_arr.shape}, expected ({n},)")
        if not np.isfinite(cap_arr).all():
            raise OptimizerError("cap_vec contains NaN/inf — refusing to build constraints")
        if ((cap_arr <= 0) | (cap_arr > 1)).any():
            raise OptimizerError("each per-asset cap must be in (0, 1]")
        if float(cap_arr.sum()) < 1 - 1e-12:
            raise OptimizerError(
                f"infeasible constraints: per-asset caps sum to {float(cap_arr.sum())} < 1 — "
                "raise some caps or add assets"
            )
    if min_vec is not None:
        min_arr = np.asarray(min_vec, dtype=float).ravel()
        if min_arr.shape != (n,):
            raise OptimizerError(f"min_vec has shape {min_arr.shape}, expected ({n},)")
        if not np.isfinite(min_arr).all():
            raise OptimizerError("min_vec contains NaN/inf — refusing to build constraints")
        if (min_arr < 0).any():
            raise OptimizerError("each per-asset min_weight must be >= 0")
        if float(min_arr.sum()) > 1 + 1e-12:
            raise OptimizerError(
                f"infeasible constraints: per-asset minimums sum to {float(min_arr.sum())} > 1"
            )
    if cap_arr is not None and min_arr is not None and (min_arr > cap_arr + 1e-12).any():
        raise OptimizerError("a per-asset min_weight exceeds its cap")
    return cap_arr, min_arr


def bounds_constraints(
    w: cp.Variable,
    cap_vec: np.ndarray | None,
    min_vec: np.ndarray | None,
    blocks: list[BlockBudget] | None,
) -> list[cp.Constraint]:
    """Long-only + sum=1 + per-asset bound vectors + block budgets.

    Always enforces ``w >= 0`` and ``cp.sum(w) == 1`` (the universal contract).
    Per-asset bounds (when given) replace the scalar cap/min. Block budgets add
    ``lo <= Σ_{i in block} wᵢ <= hi`` per group.

    Fail-loud pre-solve infeasibility checks (raised as ``OptimizerError`` so
    they never reach the solver as a silent ``infeasible`` status):
    - an empty block index list ("empty");
    - a block floor exceeds the max attainable group sum under the caps
      ("block floor" — singular);
    - the sum of block floors exceeds 1 ("block floors" — plural).
    """
    n = int(w.shape[0])
    cap_arr, min_arr = _check_bound_vectors(n, cap_vec, min_vec)
    cons: list[cp.Constraint] = [w >= 0, cp.sum(w) == 1]
    if cap_arr is not None:
        cons.append(w <= cap_arr)
    if min_arr is not None:
        cons.append(w >= min_arr)
    if blocks:
        for b in blocks:
            if not b.indices:
                raise OptimizerError("block budget has an empty index list")
            if len(set(b.indices)) != len(b.indices):
                raise OptimizerError(
                    "block budget has duplicate indices — each asset must appear at most once"
                )
            for idx in b.indices:
                if not 0 <= idx < n:
                    raise OptimizerError(f"block index {idx} out of range (n={n})")
            if not (0.0 <= b.lo <= b.hi <= 1.0):
                raise OptimizerError(
                    f"block budget bounds must satisfy 0 <= lo <= hi <= 1, got "
                    f"[{b.lo}, {b.hi}]"
                )
            if b.lo > 0:
                if cap_arr is not None:
                    max_attainable = float(min(cap_arr[b.indices].sum(), 1.0))
                else:
                    max_attainable = float(min(len(b.indices), 1.0))
                if b.lo > max_attainable + 1e-12:
                    raise OptimizerError(
                        f"infeasible constraints: block floor {b.lo} exceeds the maximum "
                        f"attainable sum {max_attainable} of its {len(b.indices)} assets under "
                        "their caps — lower the floor or raise the caps"
                    )
            group_sum = cp.sum(w[b.indices])
            cons.append(group_sum >= b.lo)
            cons.append(group_sum <= b.hi)
        if sum(b.lo for b in blocks) > 1 + 1e-12:
            raise OptimizerError(
                f"infeasible constraints: block floors sum to {sum(b.lo for b in blocks)} > 1 — "
                "sum(w)=1 cannot satisfy all minimums"
            )
    return cons


def _verify_constraints(
    weights: np.ndarray, cap: float | None, min_weight: float | None
) -> tuple[bool, str]:
    """Post-solve re-verification of the realized weight vector.

    Returns (ok, reason). ``ok`` is False with a human reason on the first
    violation (long-only, sum=1, cap, min_weight); empty reason when valid.
    """
    w = np.asarray(weights, dtype=float).ravel()
    if (w < -_WEIGHT_ATOL).any():
        return False, f"negative weight {float(w.min())}"
    total = float(w.sum())
    if abs(total - 1.0) > 1e-4:
        return False, f"weights sum to {total}, expected 1"
    if cap is not None and (w > cap + 1e-6).any():
        return False, f"cap {cap} violated (max weight {float(w.max())})"
    if min_weight is not None and (w < min_weight - 1e-6).any():
        return False, f"min_weight {min_weight} violated (min weight {float(w.min())})"
    return True, ""


def _finalize(
    problem: cp.Problem,
    w: cp.Variable,
    label: str,
    cap: float | None = None,
    min_weight: float | None = None,
    with_telemetry: bool = False,
) -> tuple[np.ndarray, str] | tuple[np.ndarray, str, SolveTelemetry]:
    """Solve with an SCS fallback ladder, demand ``optimal``, clean numerical
    noise, then RE-VERIFY the realized constraints before returning.

    Returns ``(weights, status)`` by default; with ``with_telemetry=True``
    returns ``(weights, status, SolveTelemetry)``.
    """
    used_fallback = False
    last_status = "unknown"
    solver_name = _SOLVER_LADDER[0]
    for i, solver in enumerate(_SOLVER_LADDER):
        try:
            problem.solve(solver=solver)
        except cp.error.SolverError:  # pragma: no cover - solver-dependent
            last_status = "solver_error"
            used_fallback = i > 0
            continue
        last_status = str(problem.status)
        solver_name = solver
        used_fallback = i > 0
        if last_status == cp.OPTIMAL and w.value is not None:
            break
    if last_status != cp.OPTIMAL:
        raise OptimizerError(f"{label}: solver status '{last_status}' (expected 'optimal')")
    if w.value is None:  # pragma: no cover - defensive
        raise OptimizerError(f"{label}: solver returned no solution")

    weights = np.asarray(w.value, dtype=float).ravel()
    weights[np.abs(weights) < 1e-10] = 0.0
    if (weights < -_WEIGHT_ATOL).any():
        raise OptimizerError(f"{label}: negative weight in solution: {weights.min()}")
    weights = np.clip(weights, 0.0, None)
    total = float(weights.sum())
    if abs(total - 1.0) > 1e-4:
        raise OptimizerError(f"{label}: weights sum to {total}, expected 1")
    weights = weights / total

    ok, reason = _verify_constraints(weights, cap, min_weight)
    if not ok:
        raise OptimizerError(f"{label}: post-solve constraint check failed: {reason}")

    if with_telemetry:
        telemetry = SolveTelemetry(
            solver=solver_name,
            status=last_status,
            used_fallback=used_fallback,
            realized_sum=float(weights.sum()),
            realized_max_weight=float(weights.max()),
            n_assets=int(weights.size),
        )
        return weights, last_status, telemetry
    return weights, last_status


def _validate_sigma(sigma: np.ndarray, label: str) -> np.ndarray:
    sigma = np.asarray(sigma, dtype=float)
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise OptimizerError(f"{label}: sigma must be square, got shape {sigma.shape}")
    if not np.isfinite(sigma).all():
        raise OptimizerError(f"{label}: sigma contains NaN/inf")
    return np.asarray((sigma + sigma.T) / 2.0)


def repair_psd(sigma: np.ndarray, kappa_target: float = 1e4) -> np.ndarray:
    """Symmetrize Σ and floor its eigenvalues to enforce PSD + conditioning.

    Ported from the legacy factor covariance assembler
    (quant_engine/factor_model_service.py:706-723). The eigenvalue floor is
    ``max(1e-10, max_eigval / kappa_target)``: any eigenvalue below it (including
    negatives from numerical drift or shrinkage) is clamped up, bounding the
    condition number κ = λ_max/λ_min at ``kappa_target``. A matrix already inside
    the band is returned unchanged (up to symmetrization).

    Raises:
        OptimizerError: if ``sigma`` is non-square, contains NaN/inf, or
            ``kappa_target`` is not > 1.
    """
    sigma = _validate_sigma(sigma, "repair_psd")  # square + finite + symmetrize
    if not kappa_target > 1.0:
        raise OptimizerError(f"kappa_target must be > 1, got {kappa_target}")
    eigvals, eigvecs = np.linalg.eigh(sigma)
    max_eigval = float(eigvals.max())
    clamp_val = max(1e-10, max_eigval / kappa_target)
    if eigvals.min() < clamp_val:
        eigvals = np.maximum(eigvals, clamp_val)
        sigma = eigvecs @ np.diag(eigvals) @ eigvecs.T
        sigma = (sigma + sigma.T) / 2.0
    return np.asarray(sigma, dtype=float)


def solve_equal_weight(
    n_assets: int,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """1/n weights (closed form). Constraints still validated for feasibility."""
    _check_constraint_params(n_assets, cap, min_weight)
    w = np.full(n_assets, 1.0 / n_assets)
    if cap is not None and w[0] > cap + 1e-12:  # pragma: no cover - caught above
        raise OptimizerError(f"equal_weight: 1/{n_assets} exceeds cap {cap}")
    if min_weight is not None and w[0] < min_weight - 1e-12:
        raise OptimizerError(f"equal_weight: 1/{n_assets} below min_weight {min_weight}")
    return w, "optimal"


def solve_min_vol(
    sigma: np.ndarray,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Minimum-variance portfolio: min wᵀΣw."""
    sigma = _validate_sigma(sigma, "min_vol")
    n = sigma.shape[0]
    _check_constraint_params(n, cap, min_weight)
    w = cp.Variable(n)
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))),
        base_constraints(w, cap, min_weight),
    )
    return _finalize(problem, w, "min_vol", cap=cap, min_weight=min_weight)


def solve_erc(
    sigma: np.ndarray,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Equal Risk Contribution via Spinu's convex formulation.

    Solve over the unnormalized variable y > 0:
        min ½ yᵀΣy − (1/n)·Σᵢ log(yᵢ)
    whose unique optimum, normalized (w = y/Σy), is the exact long-only ERC
    portfolio. Cap / min-weight are imposed as the LINEAR constraints
    yᵢ ≤ cap·Σy and yᵢ ≥ min_weight·Σy (equivalent to wᵢ ≤ cap, wᵢ ≥ min after
    normalization), preserving convexity; when a cap binds, the result is the
    natural constrained risk-parity projection.
    """
    sigma = _validate_sigma(sigma, "erc")
    n = sigma.shape[0]
    _check_constraint_params(n, cap, min_weight)
    y = cp.Variable(n, pos=True)
    objective = cp.Minimize(0.5 * cp.quad_form(y, cp.psd_wrap(sigma)) - cp.sum(cp.log(y)) / n)
    cons: list[cp.Constraint] = []
    if cap is not None:
        cons.append(y <= cap * cp.sum(y))
    if min_weight is not None and min_weight > 0:
        cons.append(y >= min_weight * cp.sum(y))
    problem = cp.Problem(objective, cons)
    try:
        problem.solve()
    except cp.error.SolverError as exc:  # pragma: no cover - solver-dependent
        raise OptimizerError(f"erc: solver error: {exc}") from exc
    status = str(problem.status)
    if status != cp.OPTIMAL:
        raise OptimizerError(f"erc: solver status '{status}' (expected 'optimal')")
    y_val = np.asarray(y.value, dtype=float).ravel()
    if (y_val <= 0).any():  # pragma: no cover - log barrier guarantees positivity
        raise OptimizerError("erc: non-positive y in solution")
    weights = y_val / y_val.sum()
    return weights, status


def solve_max_diversification(
    sigma: np.ndarray,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Most-diversified portfolio: max (wᵀσ)/√(wᵀΣw) (Choueifaty–Coignard).

    Convex transform: min yᵀΣy s.t. σᵀy = 1, y ≥ 0, then w = y/Σy.
    Cap / min-weight enter as the linear constraints yᵢ ≤ cap·Σy,
    yᵢ ≥ min_weight·Σy (exact in the normalized space).
    """
    sigma = _validate_sigma(sigma, "max_diversification")
    n = sigma.shape[0]
    _check_constraint_params(n, cap, min_weight)
    vols = np.sqrt(np.diag(sigma))
    if (vols <= 0).any():
        raise OptimizerError("max_diversification: an asset has zero variance")
    y = cp.Variable(n)
    cons: list[cp.Constraint] = [y >= 0, vols @ y == 1]
    if cap is not None:
        cons.append(y <= cap * cp.sum(y))
    if min_weight is not None and min_weight > 0:
        cons.append(y >= min_weight * cp.sum(y))
    problem = cp.Problem(cp.Minimize(cp.quad_form(y, cp.psd_wrap(sigma))), cons)
    try:
        problem.solve()
    except cp.error.SolverError as exc:  # pragma: no cover - solver-dependent
        raise OptimizerError(f"max_diversification: solver error: {exc}") from exc
    status = str(problem.status)
    if status != cp.OPTIMAL:
        raise OptimizerError(
            f"max_diversification: solver status '{status}' (expected 'optimal')"
        )
    y_val = np.asarray(y.value, dtype=float).ravel()
    y_val = np.clip(y_val, 0.0, None)
    total = float(y_val.sum())
    if total <= 0:  # pragma: no cover - defensive
        raise OptimizerError("max_diversification: degenerate solution (sum y = 0)")
    return y_val / total, status


def solve_min_cvar(
    scenarios: np.ndarray,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    bounds: BoundsBundle | None = None,
    current_weights: np.ndarray | None = None,
    turnover_lambda: float = 0.0,
    ret_floor: float | None = None,
    mu: np.ndarray | None = None,
    cvar_limit: float | None = None,
) -> tuple[np.ndarray, str]:
    """Min-CVaR (Rockafellar–Uryasev) on historical daily scenarios (T×n).

        min  z + 1/((1−α)·T) · Σₜ max(−rₜᵀw − z, 0)

    ``scenarios`` are raw (or BL-re-centered) daily return rows — μ-free by
    default. The optional return floor ``muᵀw ≥ ret_floor`` requires an
    EXPLICIT ``mu`` vector (annualized, from the BL posterior — gate G5: this
    function never estimates a mean itself).

    The optional ``cvar_limit`` (positive loss magnitude) adds the hard
    constraint CVaR_α(w) ≤ cvar_limit; infeasibility fails loud via the solver
    status (gate G5: no mean involved).
    """
    scenarios = np.asarray(scenarios, dtype=float)
    if scenarios.ndim != 2:
        raise OptimizerError(f"scenarios must be T×n, got ndim={scenarios.ndim}")
    if not np.isfinite(scenarios).all():
        raise OptimizerError("scenarios contain NaN/inf")
    t, n = scenarios.shape
    if t < 10:
        raise OptimizerError(f"min_cvar requires at least 10 scenarios, got {t}")
    if not 0 < alpha < 1:
        raise OptimizerError(f"alpha must be in (0, 1), got {alpha}")
    if ret_floor is not None and mu is None:
        raise OptimizerError(
            "min_cvar: ret_floor requires an explicit mu vector (BL posterior) — "
            "historical means are never estimated here (gate G5)"
        )
    if turnover_lambda < 0:
        raise OptimizerError(f"min_cvar: turnover_lambda must be >= 0, got {turnover_lambda}")
    w0: np.ndarray | None = None
    if turnover_lambda > 0:
        if current_weights is None:
            raise OptimizerError(
                "min_cvar: turnover_lambda requires current_weights (the existing "
                "portfolio allocation to penalize trading away from)"
            )
        w0 = np.asarray(current_weights, dtype=float).ravel()
        if w0.shape != (n,):
            raise OptimizerError(
                f"min_cvar: current_weights has shape {w0.shape}, expected ({n},)"
            )

    w = cp.Variable(n)
    z = cp.Variable()
    losses = -scenarios @ w  # per-scenario loss
    cvar = z + cp.sum(cp.pos(losses - z)) / ((1 - alpha) * t)
    if bounds is not None:
        cons = bounds_constraints(w, bounds.cap_vec, bounds.min_vec, bounds.blocks)
    else:
        _check_constraint_params(n, cap, min_weight)
        cons = base_constraints(w, cap, min_weight)
    if ret_floor is not None and mu is not None:
        mu_arr = np.asarray(mu, dtype=float).ravel()
        if mu_arr.shape != (n,):
            raise OptimizerError(f"min_cvar: mu has shape {mu_arr.shape}, expected ({n},)")
        cons.append(mu_arr @ w >= ret_floor)

    if cvar_limit is not None:
        if not cvar_limit > 0:
            raise OptimizerError(
                f"min_cvar: cvar_limit must be > 0 (loss magnitude), got {cvar_limit}"
            )
        # cvar is the RU loss expression (return-space loss; positive = loss).
        # Cap it at the regime-adjusted limit; infeasibility -> solver status
        # not optimal -> _finalize raises OptimizerError (fail-loud).
        cons.append(cvar <= cvar_limit)

    objective_expr = cvar
    if turnover_lambda > 0 and w0 is not None:
        objective_expr = cvar + turnover_lambda * cp.norm1(w - w0)

    problem = cp.Problem(cp.Minimize(objective_expr), cons)
    # Re-verify against the SCALAR (cap, min_weight) block only when it is the
    # active constraint set. With a BoundsBundle the realized weights are bound
    # by per-asset vectors / block budgets (not the scalar cap), so passing the
    # default scalar cap here would spuriously reject valid solutions.
    if bounds is not None:
        return _finalize(problem, w, "min_cvar")
    return _finalize(problem, w, "min_cvar", cap=cap, min_weight=min_weight)


def _realized_cvar(
    weights: np.ndarray, scenarios: np.ndarray, alpha: float
) -> float:
    """Empirical CVaR_α (loss-space, positive = loss) of realized weights.

    Exact Rockafellar-Uryasev estimator (port of the legacy
    ``ru_cvar_lp.realized_cvar_from_weights``): the LP optimum at the k-th
    worst loss. Used as the post-solve verifier for the CVaR-constraint path,
    where the in-LP (z, slack) auxiliaries only UPPER-BOUND the CVaR and can
    over-estimate, so the cap is re-checked on the realized weights. Uses
    ``np.partition`` (no sample mean) — gate G5 structural guard safe.
    """
    weights = np.asarray(weights, dtype=float).ravel()
    scenarios = np.asarray(scenarios, dtype=float)
    t = scenarios.shape[0]
    if t == 0:
        raise OptimizerError("scenarios must have at least one row")
    if not 0 < alpha < 1:
        raise OptimizerError(f"alpha must be in (0, 1), got {alpha}")
    losses = -scenarios @ weights
    k = max(int(np.ceil(np.round((1.0 - alpha) * t, 8))), 1)
    var_threshold = float(np.partition(losses, -k)[-k])
    u = np.maximum(losses - var_threshold, 0.0)
    return float(var_threshold + u.sum() / ((1.0 - alpha) * t))


def _solve_with_ladder(
    problem: cp.Problem, w: cp.Variable, label: str
) -> tuple[np.ndarray, str]:
    """Solve trying CLARABEL then SCS (legacy optimizer_service ladder).

    Accepts ``optimal`` and ``optimal_inaccurate`` (SCS often returns the
    latter on a feasible problem). Any other terminal status across BOTH
    solvers is a fail-loud ``OptimizerError``. Reimplements ``_finalize``'s
    noise cleanup / sum=1 verification because ``_finalize`` calls
    ``problem.solve()`` with no solver argument.
    """
    last_status = "no_solver_ran"
    for solver in _SOLVER_LADDER:
        try:
            problem.solve(solver=solver)
        except cp.error.SolverError:
            continue
        last_status = str(problem.status)
        if last_status in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE) and w.value is not None:
            weights = np.asarray(w.value, dtype=float).ravel()
            weights[np.abs(weights) < 1e-10] = 0.0
            if (weights < -_WEIGHT_ATOL).any():
                continue
            weights = np.clip(weights, 0.0, None)
            total = float(weights.sum())
            if total <= 0 or abs(total - 1.0) > 1e-3:
                continue
            return weights / total, "optimal"
    raise OptimizerError(
        f"{label}: no solver in {list(_SOLVER_LADDER)} produced a usable "
        f"solution (last status '{last_status}')"
    )


def solve_max_return_cvar_capped(
    scenarios: np.ndarray,
    mu: np.ndarray,
    cvar_limit: float,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    bounds: BoundsBundle | None = None,
    cvar_tol: float = 1e-4,
) -> tuple[np.ndarray, str]:
    """Max-return s.t. CVaR_α(w) ≤ ``cvar_limit`` (Rockafellar-Uryasev cap).

        max  μᵀw      s.t.  z + 1/((1−α)·T)·Σ max(−rₜᵀw − z, 0) ≤ cvar_limit,
                            long-only, sum(w)=1, caps/min/blocks.

    ``cvar_limit`` is expressed in the **same daily-return units as the
    scenarios** (e.g. 0.02 = 2% daily CVaR_95).  It is NOT an annualised
    figure.  The caller (``run_optimize``) owns the unit contract; the engine
    never rescales it.

    Gate G5: ``mu`` (annualized expected returns) is REQUIRED and never
    estimated here — by contract it is the Black-Litterman posterior. The
    in-LP CVaR auxiliaries only upper-bound the realized CVaR, so the solved
    weights are re-verified with ``_realized_cvar``; a breach beyond
    ``cvar_tol`` fails loud. Solver ladder: CLARABEL then SCS.
    """
    scenarios = np.asarray(scenarios, dtype=float)
    if scenarios.ndim != 2:
        raise OptimizerError(f"scenarios must be T×n, got ndim={scenarios.ndim}")
    if not np.isfinite(scenarios).all():
        raise OptimizerError("scenarios contain NaN/inf")
    t, n = scenarios.shape
    if t < 10:
        raise OptimizerError(f"max_return_cvar requires at least 10 scenarios, got {t}")
    if not 0 < alpha < 1:
        raise OptimizerError(f"alpha must be in (0, 1), got {alpha}")
    if mu is None:
        raise OptimizerError(
            "max_return_cvar: mu is required (BL posterior) — historical means are "
            "never estimated here (gate G5)"
        )
    mu_arr = np.asarray(mu, dtype=float).ravel()
    if mu_arr.shape != (n,):
        raise OptimizerError(f"max_return_cvar: mu has shape {mu_arr.shape}, expected ({n},)")
    if not np.isfinite(mu_arr).all():
        raise OptimizerError("max_return_cvar: mu contains NaN/inf — BL posterior is invalid")
    if cvar_limit <= 0:
        raise OptimizerError(f"max_return_cvar: cvar_limit must be > 0, got {cvar_limit}")

    w = cp.Variable(n)
    z = cp.Variable()
    losses = -scenarios @ w
    cvar_expr = z + cp.sum(cp.pos(losses - z)) / ((1 - alpha) * t)
    if bounds is not None:
        cons = bounds_constraints(w, bounds.cap_vec, bounds.min_vec, bounds.blocks)
    else:
        _check_constraint_params(n, cap, min_weight)
        cons = base_constraints(w, cap, min_weight)
    cons.append(cvar_expr <= cvar_limit)
    problem = cp.Problem(cp.Maximize(mu_arr @ w), cons)
    weights, status = _solve_with_ladder(problem, w, "max_return_cvar")
    realized = _realized_cvar(weights, scenarios, alpha)
    if realized > cvar_limit + cvar_tol:
        raise OptimizerError(
            f"max_return_cvar: solved weights realize CVaR {realized:.6f} > limit "
            f"{cvar_limit} (tol {cvar_tol}) — the solver returned an inaccurate point"
        )
    return weights, status
