"""Gate-vs-Full backtest com Black-Litterman: custo do gate fund_nav (2 anos)
vs nav_timeseries (histórico completo), usando o MOTOR + BL DE PRODUÇÃO.

Walk-forward mensal, long-only. Para cada rebalance, janela de estimação:
  GATE = 504 pregões (≈ o que o fund_nav expõe)  |  FULL = expanding (nav_timeseries)

Métodos (todos do repo, app.optimizer.*):
  cvar    = min-CVaR μ-free (cenários crus)
  minvol  = min-variância (Ledoit-Wolf)
  bl_cvar = PIPELINE BL DEFAULT: π=δΣw_mkt → views(momentum 12-1) → posterior μ_BL
            → cenários re-centrados em μ_BL → min-CVaR
  bl_util = BL max-utility: max μ_BLᵀw − (δ/2)wᵀΣ_BLw

Market weights: 1/n (sem AUM histórico em nav_timeseries; AUM atual seria look-ahead).
Views: momentum 12-1 anualizado, confidence 0.5 (sinal sistemático, igual p/ gate e full).
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from app.optimizer.engine import solve_min_cvar, solve_min_vol, sigma_ledoit_wolf, OptimizerError
from app.optimizer.black_litterman import (
    equilibrium, build_view_matrices, omega_idzorek, posterior,
    historical_mean_ann, recenter_scenarios, solve_bl_utility, AbsoluteView,
)

CSV = "_navdata.csv"
GATE_DAYS = 504
ALPHA = 0.95
COST_BPS = float(os.environ.get("COST_BPS", "10.0"))
OOS_START = "2008-01-01"
CLIP = 0.40
EQUITY_VOL_THRESHOLD = 0.08
DELTA, TAU, VIEW_CONF = 2.5, 0.05, 0.5
MOM_LB, MOM_SKIP = 252, 21

# Market weights do BL: AUM real via cascata funds_v (snapshot atual como proxy
# constante — AUM histórico por data não existe; pesos relativos são estáveis).
AUM = {
    "5cb06f3a-1466-4129-abc3-b43b14289b68": 44059740, "ec318a68-3480-4776-9969-5c7d5e00c0f6": 3084291035,
    "173e3c05-7868-4c0e-b587-3b89140c7150": 137300000, "a3451875-04b9-4a7f-ab22-2c3b7bbab6f5": 301500000,
    "b095cac2-895d-4755-be4d-3e49f65624fb": 1886359815, "e7eeb21b-4f6b-4bfd-b840-426aa836cefd": 329310530,
    "b492f90c-6f06-43c7-b4d7-25063a79a83b": 260127649, "44407097-a64e-4a42-8731-9f0930a379b4": 24209870,
    "8086c3c5-838d-43ce-b0fa-75d0b8cd785d": 1547264215, "54aff312-54ad-4633-be5f-1e354dd061b7": 1314868675,
    "354c95ba-c013-406b-aa43-543296391b73": 59764166, "0375c508-3e76-45c8-ac77-769f2d02d7ba": 191068711,
    "cc0aefb4-7bfc-4c09-b655-86cecdcca754": 719648014, "d29489fa-2f31-4f45-8f62-5ab5949392a3": 49163578,
    "1d78509b-b2d0-47b7-8b69-86b548612607": 150200046, "35643b8f-50e0-4d7a-9be7-2c5170bef6fd": 24958946,
    "2a69f1d5-5591-45c8-a9ed-69cd516a4d98": 936017060, "315d04c6-63da-4f2f-8dcf-4aef77b0d3cb": 86913193,
    "3a12e8e0-b23e-4432-80c2-55775d4072bf": 1344207001, "4201cb6a-0208-4632-a532-f4e1a0d6d47b": 101332719,
    "87fbe2b6-a852-4447-ae3a-5583d19e05e2": 226055908, "f4f95e76-75af-4fc3-b5a7-dc68893f4e0c": 419582608,
}


def momentum_views(window: pd.DataFrame):
    seg = window.iloc[-MOM_LB:-MOM_SKIP] if MOM_SKIP else window.iloc[-MOM_LB:]
    cum = (1.0 + seg).prod() - 1.0
    ann = (1.0 + cum) ** (252.0 / len(seg)) - 1.0
    ann = ann.clip(-0.6, 1.5)  # sanidade contra outliers de momentum
    return [AbsoluteView(asset=i, q=float(ann.iloc[i]), confidence=VIEW_CONF)
            for i in range(window.shape[1])]


def bl_inputs(window: pd.DataFrame):
    X = window.to_numpy()
    sigma = sigma_ledoit_wolf(X)
    aums = np.array([AUM[c] for c in window.columns], dtype=float)
    w_mkt = aums / aums.sum()  # market weights = AUM real normalizado (cascata funds_v)
    pi = equilibrium(sigma, w_mkt, DELTA)
    views = momentum_views(window)
    P, Q = build_view_matrices(views, sigma.shape[0])
    Omega = omega_idzorek(P, sigma, [v.confidence for v in views], TAU)
    mu_bl, sigma_bl = posterior(sigma, pi, P, Q, Omega, TAU)
    return mu_bl, sigma_bl, X


def weights(method, window, cap):
    if method == "cvar":
        w, _ = solve_min_cvar(window.to_numpy(), alpha=ALPHA, cap=cap)
    elif method == "minvol":
        w, _ = solve_min_vol(sigma_ledoit_wolf(window.to_numpy()), cap=cap)
    elif method == "bl_cvar":
        mu_bl, _, X = bl_inputs(window)
        rc = recenter_scenarios(X, historical_mean_ann(X), mu_bl)
        w, _ = solve_min_cvar(rc, alpha=ALPHA, cap=cap)
    else:  # bl_util
        mu_bl, sigma_bl, _ = bl_inputs(window)
        w, _ = solve_bl_utility(mu_bl, sigma_bl, DELTA, cap=cap)
    return w


def metrics(daily: pd.Series) -> dict:
    daily = daily.dropna()
    eq = (1.0 + daily).cumprod()
    sd = daily.std(ddof=1)
    return {"CAGR": eq.iloc[-1] ** (252.0 / len(daily)) - 1.0, "Vol": sd * np.sqrt(252),
            "Sharpe": (daily.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan"),
            "MaxDD": (eq / eq.cummax() - 1.0).min()}


def run_strategy(R, rebal, method, mode, cap):
    n = R.shape[1]
    w_prev = np.zeros(n)
    daily = pd.Series(0.0, index=R.index, dtype=float)
    turn, n_ok, n_fb, active = [], 0, 0, []
    rb = list(rebal)
    for i, t in enumerate(rb):
        hist = R.loc[:t]
        window = hist.tail(GATE_DAYS) if mode == "gate" else hist
        try:
            w = weights(method, window, cap)
            n_ok += 1
        except (OptimizerError, ValueError, np.linalg.LinAlgError):
            n_fb += 1
            w = w_prev if w_prev.sum() > 0 else np.full(n, 1.0 / n)
        turn.append(float(np.abs(w - w_prev).sum()))
        active.append(int((w > 1e-4).sum()))
        end = rb[i + 1] if i + 1 < len(rb) else R.index[-1]
        seg = R.loc[t:end].iloc[1:]
        if len(seg):
            sr = seg.to_numpy() @ w
            sr[0] -= turn[-1] * COST_BPS / 1e4
            daily.loc[seg.index] = sr
        w_prev = w
    m = metrics(daily.loc[OOS_START:])
    m.update(turnover=float(np.mean(turn)), n_ok=n_ok, n_fb=n_fb, active=float(np.mean(active)))
    return m


def scenario(R, rebal, label, cap, methods):
    print(f"\n===== {label} | {R.shape[1]} ativos | cap {cap} =====")
    for method in methods:
        res = {}
        for mode in ["gate", "full"]:
            m = run_strategy(R, rebal, method, mode, cap)
            res[mode] = m
            print(f"{method:7} {mode:4} | CAGR {m['CAGR']*100:6.2f}% | Vol {m['Vol']*100:5.2f}% | "
                  f"Sharpe {m['Sharpe']:5.2f} | MaxDD {m['MaxDD']*100:7.2f}% | turn {m['turnover']:.3f} | "
                  f"pos {m['active']:.1f} | ok {m['n_ok']} fb {m['n_fb']}")
        g, f = res["gate"], res["full"]
        print(f"        Δ full−gate | CAGR {(f['CAGR']-g['CAGR'])*100:+6.2f}pp | "
              f"Sharpe {f['Sharpe']-g['Sharpe']:+5.2f} | MaxDD {(f['MaxDD']-g['MaxDD'])*100:+6.2f}pp")


def main():
    df = pd.read_csv(CSV)
    df = df[["id", "nav_date", "return_1d"]] if "nav_date" in df.columns else df
    df.columns = ["id", "date", "ret"]
    R = df.pivot(index="date", columns="id", values="ret").astype(float).clip(-CLIP, CLIP).dropna()
    R.index = pd.to_datetime(R.index)
    ann_vol = R.std(ddof=1) * np.sqrt(252)
    eq_cols = ann_vol[ann_vol >= EQUITY_VOL_THRESHOLD].index.tolist()
    idx = R.index
    last = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).transform("max")
    rebal = idx[idx == last.values]
    rebal = rebal[rebal >= "2006-02-01"]
    print(f"[dados] {R.shape[1]} fundos | {R.index.min().date()}->{R.index.max().date()} | "
          f"{len(R)} pregões | {len(rebal)} rebalances | OOS {OOS_START} | custo {COST_BPS}bps")

    methods = ["cvar", "minvol", "bl_cvar", "bl_util"]
    scenario(R[eq_cols], rebal, "EQUITIES-ONLY", 0.35, methods)
    scenario(R, rebal, "TODOS", 0.25, methods)


if __name__ == "__main__":
    main()
