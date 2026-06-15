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

TRADING_DAYS = 252

DEFAULT_CAP = 0.25
DEFAULT_CVAR_ALPHA = 0.95

_WEIGHT_ATOL = 1e-6


class OptimizerError(ValueError):
    """Solver failed / problem infeasible / invalid inputs. Mapped to 422."""


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


def _finalize(problem: cp.Problem, w: cp.Variable, label: str) -> tuple[np.ndarray, str]:
    """Solve, demand ``optimal``, clean tiny numerical noise, verify sum=1."""
    try:
        problem.solve()
    except cp.error.SolverError as exc:  # pragma: no cover - solver-dependent
        raise OptimizerError(f"{label}: solver error: {exc}") from exc
    status = str(problem.status)
    if status != cp.OPTIMAL:
        raise OptimizerError(f"{label}: solver status '{status}' (expected 'optimal')")
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
    return weights, status


def _validate_sigma(sigma: np.ndarray, label: str) -> np.ndarray:
    sigma = np.asarray(sigma, dtype=float)
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise OptimizerError(f"{label}: sigma must be square, got shape {sigma.shape}")
    if not np.isfinite(sigma).all():
        raise OptimizerError(f"{label}: sigma contains NaN/inf")
    return np.asarray((sigma + sigma.T) / 2.0)


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
    return _finalize(problem, w, "min_vol")


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
    ret_floor: float | None = None,
    mu: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
    """Min-CVaR (Rockafellar–Uryasev) on historical daily scenarios (T×n).

        min  z + 1/((1−α)·T) · Σₜ max(−rₜᵀw − z, 0)

    ``scenarios`` are raw (or BL-re-centered) daily return rows — μ-free by
    default. The optional return floor ``muᵀw ≥ ret_floor`` requires an
    EXPLICIT ``mu`` vector (annualized, from the BL posterior — gate G5: this
    function never estimates a mean itself).
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
    _check_constraint_params(n, cap, min_weight)
    if ret_floor is not None and mu is None:
        raise OptimizerError(
            "min_cvar: ret_floor requires an explicit mu vector (BL posterior) — "
            "historical means are never estimated here (gate G5)"
        )

    w = cp.Variable(n)
    z = cp.Variable()
    losses = -scenarios @ w  # per-scenario loss
    cvar = z + cp.sum(cp.pos(losses - z)) / ((1 - alpha) * t)
    cons = base_constraints(w, cap, min_weight)
    if ret_floor is not None and mu is not None:
        mu_arr = np.asarray(mu, dtype=float).ravel()
        if mu_arr.shape != (n,):
            raise OptimizerError(f"min_cvar: mu has shape {mu_arr.shape}, expected ({n},)")
        cons.append(mu_arr @ w >= ret_floor)
    problem = cp.Problem(cp.Minimize(cvar), cons)
    return _finalize(problem, w, "min_cvar")
