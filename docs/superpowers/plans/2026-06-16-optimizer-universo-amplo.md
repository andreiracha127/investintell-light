# Optimizer sobre universo amplo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o optimizer enxergue todo o universo filtrado (Gates 1–3, sem cap de ranking) e ainda entregue um portfólio enxuto (~20–40 posições) via um pipeline de dois estágios (seleção por estrutura de risco → alocação convexa).

**Architecture:** Pipeline de dois estágios construído **por cima de `feat/quant-port-tier3`**. Estágio 1 (seleção) carrega retornos T×N **sem dropna global**, estima **covariância pairwise** (máscara de disponibilidade), denoise via RMT (`marchenko_pastur_denoise` + `ledoit_wolf_constant_correlation` do Tier 3), repara PSD (`repair_psd`/`_validate_sigma`), e escolhe K representantes por **clustering hierárquico aglomerativo** sobre distância `1−ρ` com desempate por **score de qualidade G5-safe** (Sharpe_1y↑/expense↓/AUM↑). Estágio 2 alinha os K via `load_aligned_returns` (dropna + `MIN_COMMON_OBS`), estima `sigma_robust` (RMT quando `q=N/T>0.5`, senão Ledoit-Wolf) e resolve via o engine existente (`solve_min_cvar`/BL/ERC) sem mudar a interface dos `solve_*`.

**Tech Stack:** Python 3.13, numpy, pandas, cvxpy, scikit-learn (clustering), scipy, FastAPI, SQLAlchemy async

---

## File structure

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `backend/app/analytics/pairwise_cov.py` | **Create** | `pairwise_covariance(R, min_pair_overlap)` — cov pairwise vetorizada via máscara (sem dropna global), exclusão fail-loud de fundos com overlap mediano abaixo do limiar, `<2` viáveis → `ValueError`. Puro numpy. |
| `backend/app/optimizer/selection.py` | **Create** | Estágio 1: `quality_score(...)` (normalização Sharpe↑/expense↓/AUM↑, G5-safe) + `select_diversified(corr_denoised, scores, k)` (clustering hierárquico aglomerativo 1−ρ, 1 representante/cluster) + helper de composição `robust_selection_covariance(...)` (pairwise → corr → MP denoise → PSD-repair). Puro. |
| `backend/app/optimizer/data.py` | **Modify** | Novo loader `load_returns_matrix(...)` (T×N **sem** dropna global, NaN preservado); `select_universe_funds` com `max_assets` opcional (`None` = sem LIMIT) + teto duro `MAX_UNIVERSE_CANDIDATES=2000` (fail-loud). `load_fund_quality_metrics(...)` para o score. |
| `backend/app/optimizer/engine.py` | **Modify** | `sigma_robust(returns, *, q_threshold=0.5)` — RMT path quando `q=N/T>0.5`, senão `sigma_ledoit_wolf`; sempre `repair_psd`; fallback determinístico. Não muda os `solve_*`. |
| `backend/app/services/portfolio_builder.py` | **Modify** | Orquestração modo universo-amplo: Gates 1–3 (sem cap) → `load_returns_matrix` → Estágio 1 → `load_aligned_returns` dos K → Estágio 2 (`sigma_robust` + `solve_*`). Diagnóstico de seleção no contrato de resposta. |
| `backend/app/schemas/builder.py` | **Modify** | Flag/modo universo-amplo (`broad_universe: bool`), `MAX_UNIVERSE_CANDIDATES`, `K`/`max_positions`, `min_pair_overlap`; `SelectionDiagnosticsOut` (clusters, fundos excluídos) em `DiagnosticsOut`. |
| `backend/app/api/routes/builder.py` | **Modify** (mínimo) | A rota já mapeia `BuilderError`→422; só garantir que o novo caminho continua passando por `run_optimize`. Regen de `openapi.json` + `api.d.ts` se o schema de resposta mudar. |
| `backend/tests/test_analytics_pairwise_cov.py` | **Create** | Testes T1. |
| `backend/tests/test_optimizer_selection.py` | **Create** | Testes T2/T3. |
| `backend/tests/test_optimizer_data_broad.py` | **Create** | Testes T4 (loader sem dropna + cap removido/teto). |
| `backend/tests/test_optimizer_sigma_robust.py` | **Create** | Testes T5. |
| `backend/tests/test_builder_broad_universe.py` | **Create** | Integração T6/T7 (rota end-to-end + diagnóstico). |
| `frontend/src/components/funds/FundProfileView.tsx` | **Modify** (T9, independente) | Restaurar a exibição condicional das 4 métricas FI/alt (`empirical_duration`/`credit_beta`/`inflation_beta`/`crisis_alpha_score`) que o Tier 3 T1B-8 passou a popular. |

---

## Convenções do projeto (LER ANTES DE CADA TASK)

- **Python 3.13 GLOBAL** (numpy 2.2.6 / pandas 3.0.1 / cvxpy / scikit-learn 1.8.0 / scipy 1.17.1). **Sem venv por-worktree.**
- **Comando de teste:** `cd backend && python -m pytest tests/test_<arquivo>.py::<test> -v` (`asyncio_mode=auto`; rotas usam `httpx.AsyncClient`, sem `@pytest.mark.anyio` explícito — o autouse do projeto cobre).
- **Fail-loud:** analytics puros levantam `ValueError` em dados insuficientes/NaN (NUNCA retornam NaN/None). No engine, a exceção é `OptimizerError(ValueError)`. Rotas mapeiam para **422** via `BuilderError`.
- **Gate G5 (mu-free):** NENHUM objetivo consome média amostral como retorno esperado. A seleção do Estágio 1 usa SÓ estrutura de risco (correlação) + score de qualidade (Sharpe_1y/expense/AUM dos filtros) — **NÃO** retorno esperado. O único `mu` permitido no engine vem do posterior BL (não aplicável ao modo universo-amplo, que é incompatível com `views`).
- **Escala:** frações decimais (0.05 = 5%).
- **Commits frequentes; cada task termina com commit.** Trailer em cada commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **Regen de contrato (somente se o schema de resposta mudar):** o projeto usa **pnpm** (não npm). Canônico: `make types` (roda `uv run python scripts/export_openapi.py` + `pnpm run types`). Se o frontend não tiver `node_modules` instalado, gere o `api.d.ts` diretamente:
  ```
  cd backend && python scripts/export_openapi.py
  cd frontend && pnpm dlx openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts
  ```

### Sinais de qualidade reusados (do Tier 3, NÃO re-derivar)
- `app.analytics.rmt.marchenko_pastur_denoise(corr_matrix, q)` → corr unit-diagonal denoised (PSD-clamped). `q = N/T`.
- `app.analytics.rmt.ledoit_wolf_constant_correlation(returns)` → `(cov_shrunk, delta)`. **Exige `returns` finitos** (levanta `ValueError` em NaN) — por isso o Estágio 1 usa **pairwise**, não LW direto sobre a matriz com NaN.
- `app.optimizer.engine.sigma_ledoit_wolf(returns)` → cov **anualizada ×252** (delega a `sklearn.covariance.LedoitWolf`).
- `app.optimizer.engine.repair_psd(sigma, kappa_target=1e4)` → simetriza + clampa autovalores (PSD + condicionamento). Internamente chama `_validate_sigma`.
- `app.optimizer.engine._validate_sigma(sigma, label)` → valida quadrada/finita + simetriza (levanta `OptimizerError`).

---

## Índice de tasks

- **T1** — `pairwise_covariance` puro (`app/analytics/pairwise_cov.py`).
- **T2** — Helper de covariância robusta de seleção (`robust_selection_covariance` em `app/optimizer/selection.py`): pairwise → corr → MP denoise → PSD-repair.
- **T3** — Seletor diversificação+qualidade (`quality_score` + `select_diversified` em `app/optimizer/selection.py`): clustering hierárquico aglomerativo + representante por score.
- **T4** — Seam de dados (`app/optimizer/data.py`): `load_returns_matrix` (sem dropna global) + `select_universe_funds` cap opcional + `MAX_UNIVERSE_CANDIDATES` + `load_fund_quality_metrics`.
- **T5** — `sigma_robust` no `app/optimizer/engine.py`.
- **T6** — Orquestração no `portfolio_builder.py` (Estágios 1+2 + diagnóstico).
- **T7** — Rota/schemas (`builder.py`/`schemas/builder.py`) + regen de contrato.
- **T8** — Gate de regressão full-suite.
- **T9** — (Frontend, independente) Restaurar a exibição das métricas FI/alt no `FundProfileView.tsx` (só os 4 campos que o Tier 3 T1B-8 portou).

---

## T1 — `pairwise_covariance` puro

Covariância pairwise vetorizada sobre uma matriz T×N **com NaN** (sem dropna global), com guarda de overlap mínimo e exclusão fail-loud.

**Files**
- **Create:** `backend/app/analytics/pairwise_cov.py`
- **Test:** `backend/tests/test_analytics_pairwise_cov.py`

### Passos

- [ ] **1. Write failing test.** Crie `backend/tests/test_analytics_pairwise_cov.py`:

```python
"""Unit tests for app.analytics.pairwise_cov — pairwise covariance over a
returns matrix WITH NaN (no global dropna), vectorized via an availability
mask, with a minimum-overlap guard and fail-loud exclusion.
"""

import numpy as np
import pytest

from app.analytics import pairwise_cov


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


def test_pairwise_matches_np_cov_when_no_nan() -> None:
    """With a fully-observed matrix, pairwise cov == np.cov (1/n convention)."""
    x = _factor_returns(300, 5, seed=1)
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=50)
    assert kept == [0, 1, 2, 3, 4]
    assert excluded == {}
    expected = np.cov(x, rowvar=False, bias=True)  # bias=True ⇒ /n convention
    np.testing.assert_allclose(cov, expected, atol=1e-10)


def test_pairwise_handles_known_nan_pattern() -> None:
    """A planted NaN block reduces the pair overlap; the resulting pairwise
    mean/cov match a hand-computed reference on the overlapping rows only."""
    x = _factor_returns(400, 3, seed=2)
    x[:100, 0] = np.nan  # column 0 missing its first 100 rows
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)
    assert kept == [0, 1, 2]
    assert excluded == {}
    # Reference for the (0, 1) entry: overlap is rows 100..399.
    a = x[100:, 0]
    b = x[100:, 1]
    n_ij = a.size
    ref = float((a @ b) / n_ij - (a.mean()) * (b.mean()))
    assert cov[0, 1] == pytest.approx(ref, abs=1e-10)


def test_pairwise_excludes_fund_below_overlap_threshold() -> None:
    """A column whose median pairwise overlap falls below the threshold is
    excluded (structured reason), not silently kept."""
    x = _factor_returns(400, 4, seed=3)
    x[50:, 2] = np.nan  # column 2 has only 50 observations ⇒ tiny overlaps
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)
    assert 2 not in kept
    assert kept == [0, 1, 3]
    assert 2 in excluded
    assert "overlap" in excluded[2].lower()
    assert cov.shape == (3, 3)


def test_pairwise_fails_loud_with_fewer_than_two_viable() -> None:
    x = _factor_returns(400, 3, seed=4)
    x[50:, 1] = np.nan
    x[50:, 2] = np.nan  # only column 0 keeps a long history
    with pytest.raises(ValueError, match="at least 2"):
        pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)


def test_pairwise_rejects_non_2d() -> None:
    with pytest.raises(ValueError, match=r"\(T, N\)"):
        pairwise_cov.pairwise_covariance(np.zeros(5), min_pair_overlap=10)
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_analytics_pairwise_cov.py -v` — expect `ModuleNotFoundError: No module named 'app.analytics.pairwise_cov'`.

- [ ] **3. Implement.** Crie `backend/app/analytics/pairwise_cov.py`:

```python
"""Pairwise covariance over a returns matrix WITH NaN — pure numpy, no I/O.

The Stage-1 (selection) covariance estimator. Unlike a global ``dropna`` (which
collapses the common-history window to the youngest asset), this computes each
pair's covariance on THAT pair's overlapping observations, vectorized via an
availability mask — no explicit per-pair loop.

Demeaned pairwise covariance: with ``R0 = R`` (NaN→0) and ``M`` the binary
presence mask (1 where observed), ``n_ij = MᵀM`` (overlap per pair),
``μ = (R0ᵀM) / n_ij`` (pairwise means), and
``cov_ij = (R0ᵀR0) / n_ij − μ_ij · μ_jiᵀ`` (1/n convention, matches
``np.cov(..., bias=True)`` on a fully-observed matrix).

Fail-loud: a column whose MEDIAN pairwise overlap is below ``min_pair_overlap``
is EXCLUDED with a structured reason (never silently kept); the covariance is
re-built on the surviving columns. Fewer than 2 survivors raises ``ValueError``
(routes map → 422). Scale contract: returns are decimal fractions.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

MIN_PAIR_OVERLAP = 252  # ~1 trading year (design §8)


def _pairwise_raw(
    r: NDArray[np.float64], mask: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return (cov, overlap_counts) for the given (NaN→0) matrix + mask."""
    r0 = np.where(mask > 0, r, 0.0)
    n_ij = mask.T @ mask  # (N, N) overlap counts per pair
    safe = np.where(n_ij > 0, n_ij, 1.0)
    sum_prod = r0.T @ r0  # (N, N) Σ rᵢ·rⱼ over the overlap
    sum_i = r0.T @ mask  # (N, N): row i = Σ rᵢ where j is present
    mean_ij = sum_i / safe  # μ_ij (mean of i over the (i,j) overlap)
    cov = sum_prod / safe - mean_ij * mean_ij.T
    cov = (cov + cov.T) / 2.0
    return np.asarray(cov, dtype=float), np.asarray(n_ij, dtype=float)


def pairwise_covariance(
    returns: NDArray[np.floating], min_pair_overlap: int = MIN_PAIR_OVERLAP
) -> tuple[NDArray[np.float64], list[int], dict[int, str]]:
    """Pairwise covariance of a (T, N) returns matrix with NaN.

    Parameters
    ----------
    returns : (T, N) array; NaN marks a missing observation (no dropna).
    min_pair_overlap : minimum overlap (rows) for a column's MEDIAN pairwise
        overlap; columns below it are excluded.

    Returns
    -------
    (cov, kept_indices, excluded) where ``cov`` is the (K, K) pairwise
    covariance over the surviving columns (in their original order),
    ``kept_indices`` are the surviving 0-based column indices, and ``excluded``
    maps an excluded column index → a human reason.

    Raises
    ------
    ValueError : input is not 2-D, or fewer than 2 viable columns survive.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns must be a (T, N) matrix, got ndim={arr.ndim}")
    t, n = arr.shape
    if n < 2:
        raise ValueError("at least 2 assets are required for a covariance")
    if min_pair_overlap < 1:
        raise ValueError(f"min_pair_overlap must be >= 1, got {min_pair_overlap}")

    mask = np.isfinite(arr).astype(float)
    _, n_ij = _pairwise_raw(arr, mask)

    # Per-column viability: the MEDIAN of its off-diagonal pairwise overlaps.
    excluded: dict[int, str] = {}
    kept: list[int] = []
    off_mask = ~np.eye(n, dtype=bool)
    for i in range(n):
        overlaps = n_ij[i][off_mask[i]]
        median_overlap = float(np.median(overlaps)) if overlaps.size else 0.0
        if median_overlap < min_pair_overlap:
            excluded[i] = (
                f"median pairwise overlap {median_overlap:.0f} < "
                f"{min_pair_overlap} — short-history fund excluded"
            )
        else:
            kept.append(i)

    if len(kept) < 2:
        raise ValueError(
            f"pairwise covariance needs at least 2 funds with sufficient overlap; "
            f"{len(kept)} survived (min_pair_overlap={min_pair_overlap}) — "
            "widen the window or relax the filters"
        )

    sub = arr[:, kept]
    sub_mask = np.isfinite(sub).astype(float)
    cov, _ = _pairwise_raw(sub, sub_mask)
    return cov, kept, excluded
```

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_analytics_pairwise_cov.py -v` — all green.

- [ ] **5. Commit.**
  ```
  git add backend/app/analytics/pairwise_cov.py backend/tests/test_analytics_pairwise_cov.py
  git commit -m "feat(analytics): pairwise covariance with NaN mask + overlap guard (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T2 — Helper de covariância robusta de seleção

Compõe T1 + rmt + PSD-repair num único helper que produz a **correlação denoised** consumida pelo clustering do Estágio 1.

**Files**
- **Create:** `backend/app/optimizer/selection.py` (este task adiciona apenas `robust_selection_covariance`)
- **Test:** `backend/tests/test_optimizer_selection.py` (este task adiciona apenas a classe de testes do helper)

### Passos

- [ ] **1. Write failing test.** Crie `backend/tests/test_optimizer_selection.py` com a primeira seção:

```python
"""Unit tests for app.optimizer.selection — Stage-1 robust covariance helper
and the diversification+quality selector.
"""

import numpy as np
import pytest

from app.optimizer import selection


def _planted_clusters(
    t: int = 600, per_cluster: int = 4, n_clusters: int = 3, seed: int = 0
) -> np.ndarray:
    """(T, N) returns with ``n_clusters`` blocks; each block shares a factor."""
    rng = np.random.default_rng(seed)
    cols = []
    for c in range(n_clusters):
        common = rng.standard_normal((t, 1))
        for _ in range(per_cluster):
            idio = rng.standard_normal((t, 1))
            cols.append(0.85 * common + 0.15 * idio)
    return np.hstack(cols)


# ── robust_selection_covariance ──────────────────────────────────────────────


def test_robust_selection_covariance_returns_psd_unit_diag_corr() -> None:
    x = _planted_clusters(seed=1)
    corr, kept, excluded = selection.robust_selection_covariance(
        x, min_pair_overlap=252
    )
    n = len(kept)
    assert corr.shape == (n, n)
    np.testing.assert_allclose(np.diag(corr), np.ones(n), atol=1e-8)
    np.testing.assert_allclose(corr, corr.T, atol=1e-10)
    assert np.linalg.eigvalsh(corr).min() > -1e-9  # PSD after repair
    assert excluded == {}


def test_robust_selection_covariance_excludes_short_history() -> None:
    x = _planted_clusters(seed=2)
    x[80:, 5] = np.nan  # one column with only 80 obs
    corr, kept, excluded = selection.robust_selection_covariance(
        x, min_pair_overlap=252
    )
    assert 5 not in kept
    assert 5 in excluded
    assert corr.shape == (len(kept), len(kept))
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_optimizer_selection.py -v` — expect `ModuleNotFoundError: No module named 'app.optimizer.selection'`.

- [ ] **3. Implement.** Crie `backend/app/optimizer/selection.py` (apenas o helper neste task; o seletor entra no T3):

```python
"""Stage-1 (selection) of the broad-universe optimizer — pure numpy/scipy.

Two responsibilities, both side-effect-free:

1. ``robust_selection_covariance`` — compose the pairwise covariance (with NaN,
   no global dropna) with the Tier-3 RMT denoise (Marchenko-Pastur) and the
   engine PSD-repair, returning a clean unit-diagonal CORRELATION matrix for
   clustering plus the kept/excluded bookkeeping.
2. ``quality_score`` / ``select_diversified`` — pick K representatives by
   agglomerative clustering on the denoised correlation distance ``1 − ρ``,
   one representative per cluster, ranked by a G5-safe quality score
   (Sharpe_1y↑ / expense_ratio↓ / AUM↑). NO expected-return input (gate G5).

Fail-loud: degenerate input bubbles ``ValueError`` from the underlying
primitives (routes map → 422).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from app.analytics import pairwise_cov, rmt
from app.optimizer.engine import repair_psd


def _corr_from_cov(cov: NDArray[np.float64]) -> NDArray[np.float64]:
    d = np.sqrt(np.maximum(np.diag(cov), 0.0))
    d[d == 0] = 1.0
    corr = cov / np.outer(d, d)
    np.fill_diagonal(corr, 1.0)
    return np.asarray((corr + corr.T) / 2.0, dtype=float)


def robust_selection_covariance(
    returns: NDArray[np.floating],
    min_pair_overlap: int = pairwise_cov.MIN_PAIR_OVERLAP,
) -> tuple[NDArray[np.float64], list[int], dict[int, str]]:
    """Pairwise cov → correlation → MP denoise → PSD-repair → unit-diag corr.

    Returns ``(corr_denoised, kept_indices, excluded)`` where ``corr_denoised``
    is the (K, K) cleaned correlation over the surviving columns (same order as
    ``kept_indices``). ``q = K / T_effective`` for the MP bound uses the median
    pairwise overlap of the survivors as ``T_effective`` (a conservative proxy
    for the unequal-history window).
    """
    arr = np.asarray(returns, dtype=float)
    cov, kept, excluded = pairwise_cov.pairwise_covariance(arr, min_pair_overlap)
    corr_raw = _corr_from_cov(cov)
    k = len(kept)

    sub = arr[:, kept]
    sub_mask = np.isfinite(sub).astype(float)
    n_ij = sub_mask.T @ sub_mask
    off = ~np.eye(k, dtype=bool)
    t_eff = float(np.median(n_ij[off])) if k > 1 else float(sub_mask.sum())
    t_eff = max(t_eff, 1.0)
    q = k / t_eff

    if k > 1:
        corr_denoised = rmt.marchenko_pastur_denoise(corr_raw, q)
    else:  # pragma: no cover - pairwise_covariance already guards k >= 2
        corr_denoised = corr_raw
    # PSD-repair operates on covariance-shaped matrices; a unit-diagonal corr is
    # a valid covariance, so repair_psd both floors negative eigenvalues and
    # bounds the condition number. Re-normalize the diagonal back to 1.
    repaired = repair_psd(corr_denoised)
    corr_clean = _corr_from_cov(repaired)
    return corr_clean, kept, excluded
```

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_optimizer_selection.py -v` — the two helper tests pass.

- [ ] **5. Commit.**
  ```
  git add backend/app/optimizer/selection.py backend/tests/test_optimizer_selection.py
  git commit -m "feat(optimizer): Stage-1 robust selection covariance helper (T2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T3 — Seletor diversificação+qualidade (Estágio 1)

Clustering hierárquico aglomerativo sobre `1−ρ` (scipy) + 1 representante por cluster pelo **score de qualidade** G5-safe.

**Decisão de dependência:** usar **`scipy.cluster.hierarchy`** (`linkage` + `fcluster`), que aceita uma matriz de distância condensada diretamente e é a forma mais limpa de cortar em K clusters por `maxclust`. `scipy` 1.17.1 já é dependência (confirmado). Evitamos `sklearn.cluster.AgglomerativeClustering` aqui porque cortar em exatamente K clusters via `n_clusters` exige `metric="precomputed"` + `linkage="average"` e não expõe o dendrograma para fallback — scipy é mais direto para o caso "K = min(K_alvo, n_disponível)".

**Score de qualidade (explícito, G5-safe):** dado, por fundo, `sharpe_1y`, `expense_ratio`, `aum_usd` (qualquer um pode faltar):
- normaliza cada sinal por **min-max** sobre os fundos disponíveis para aquele sinal → `[0, 1]`;
- `expense` é invertido (`1 − norm`), pois menor é melhor;
- `score = w_sharpe·s_sharpe + w_expense·s_expense + w_aum·s_aum`, defaults `w_sharpe=0.5, w_expense=0.25, w_aum=0.25` (somam 1);
- sinais ausentes recebem o valor neutro `0.5` (não penaliza nem premia);
- **NÃO** consome retorno esperado nem média amostral (gate G5).

**Files**
- **Modify:** `backend/app/optimizer/selection.py` (adiciona `quality_score`, `select_diversified`, `SelectionResult`)
- **Test:** `backend/tests/test_optimizer_selection.py` (adiciona seção do seletor)

### Passos

- [ ] **1. Write failing test.** Acrescente ao final de `backend/tests/test_optimizer_selection.py`:

```python
# ── quality_score ────────────────────────────────────────────────────────────


def test_quality_score_ranks_high_sharpe_low_expense_high_aum_first() -> None:
    metrics = [
        {"sharpe_1y": 2.0, "expense_ratio": 0.001, "aum_usd": 1e10},  # best
        {"sharpe_1y": 0.1, "expense_ratio": 0.02, "aum_usd": 1e7},  # worst
        {"sharpe_1y": 1.0, "expense_ratio": 0.01, "aum_usd": 1e8},  # mid
    ]
    scores = selection.quality_score(metrics)
    assert scores.shape == (3,)
    assert scores[0] > scores[2] > scores[1]


def test_quality_score_neutral_for_all_missing() -> None:
    metrics = [
        {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None},
        {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None},
    ]
    scores = selection.quality_score(metrics)
    np.testing.assert_allclose(scores, [0.5, 0.5], atol=1e-12)


# ── select_diversified ───────────────────────────────────────────────────────


def test_select_diversified_picks_one_per_cluster() -> None:
    """3 planted clusters of 4 ⇒ asking for K=3 returns exactly one index from
    each cluster block (0-3, 4-7, 8-11)."""
    x = _planted_clusters(per_cluster=4, n_clusters=3, seed=7)
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.linspace(0, 1, len(kept))  # arbitrary but distinct
    result = selection.select_diversified(corr, scores, k=3)
    assert len(result.selected) == 3
    blocks = {idx // 4 for idx in result.selected}
    assert blocks == {0, 1, 2}  # one representative per planted cluster
    # Every selected index carries a cluster label and its score.
    assert set(result.cluster_of) == set(result.selected)


def test_select_diversified_picks_best_quality_within_cluster() -> None:
    """Within a cluster, the highest-score member is the representative."""
    x = _planted_clusters(per_cluster=4, n_clusters=2, seed=8)
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.zeros(len(kept))
    scores[2] = 1.0  # best in cluster 0 (indices 0-3)
    scores[5] = 1.0  # best in cluster 1 (indices 4-7)
    result = selection.select_diversified(corr, scores, k=2)
    assert set(result.selected) == {2, 5}


def test_select_diversified_caps_k_at_available() -> None:
    x = _planted_clusters(per_cluster=2, n_clusters=2, seed=9)  # 4 assets
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.linspace(0, 1, len(kept))
    result = selection.select_diversified(corr, scores, k=99)  # more than N
    assert len(result.selected) == len(kept)  # cannot exceed available


def test_select_diversified_rejects_shape_mismatch() -> None:
    corr = np.eye(4)
    with pytest.raises(ValueError, match="scores"):
        selection.select_diversified(corr, np.zeros(3), k=2)
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_optimizer_selection.py -v` — expect `AttributeError: module 'app.optimizer.selection' has no attribute 'quality_score'`.

- [ ] **3. Implement.** Acrescente a `backend/app/optimizer/selection.py` (imports no topo + corpo ao final):

No topo do arquivo, junto aos imports existentes, adicione:

```python
from dataclasses import dataclass

from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
```

E ao final do arquivo:

```python
# Default quality-score weights (sum to 1). Sharpe dominates; expense/AUM tie.
_W_SHARPE = 0.5
_W_EXPENSE = 0.25
_W_AUM = 0.25
_NEUTRAL = 0.5


def _minmax(values: list[float | None], *, invert: bool) -> NDArray[np.float64]:
    """Min-max normalize a signal to [0, 1]; missing → neutral 0.5.

    ``invert=True`` flips the scale (lower raw value ⇒ higher score, e.g. the
    expense ratio). A degenerate signal (all equal / all missing) maps every
    present entry to the neutral 0.5 so it neither helps nor hurts.
    """
    arr = np.array(
        [np.nan if v is None else float(v) for v in values], dtype=float
    )
    present = np.isfinite(arr)
    out = np.full(arr.shape, _NEUTRAL, dtype=float)
    if present.sum() < 2:
        return out
    lo = float(arr[present].min())
    hi = float(arr[present].max())
    if hi - lo < 1e-12:
        return out
    norm = (arr[present] - lo) / (hi - lo)
    if invert:
        norm = 1.0 - norm
    out[present] = norm
    return out


def quality_score(
    metrics: list[dict[str, float | None]],
    *,
    w_sharpe: float = _W_SHARPE,
    w_expense: float = _W_EXPENSE,
    w_aum: float = _W_AUM,
) -> NDArray[np.float64]:
    """G5-safe per-fund quality score in [0, 1].

    ``metrics[i]`` carries ``sharpe_1y`` / ``expense_ratio`` / ``aum_usd``
    (any may be ``None``). The score combines normalized Sharpe (↑), inverted
    expense (↓ is better), and AUM (↑). NO expected-return / sample-mean input
    is consumed (gate G5).
    """
    if not metrics:
        raise ValueError("metrics must be non-empty")
    s_sharpe = _minmax([m.get("sharpe_1y") for m in metrics], invert=False)
    s_expense = _minmax([m.get("expense_ratio") for m in metrics], invert=True)
    s_aum = _minmax([m.get("aum_usd") for m in metrics], invert=False)
    return np.asarray(
        w_sharpe * s_sharpe + w_expense * s_expense + w_aum * s_aum, dtype=float
    )


@dataclass(frozen=True)
class SelectionResult:
    """Stage-1 output: chosen representatives + cluster/score bookkeeping.

    ``selected`` are 0-based indices INTO the correlation matrix passed to
    ``select_diversified`` (i.e. positions within the kept/survivor set).
    ``cluster_of`` maps each selected index → its cluster label;
    ``score_of`` maps it → its quality score.
    """

    selected: list[int]
    cluster_of: dict[int, int]
    score_of: dict[int, float]


def select_diversified(
    corr_denoised: NDArray[np.floating],
    scores: NDArray[np.floating],
    k: int,
) -> SelectionResult:
    """Pick ≤ K representatives: 1 per cluster, max quality within the cluster.

    Agglomerative (average-linkage) clustering on the distance ``d = 1 − ρ``
    over the denoised correlation, cut into ``min(k, N)`` clusters; the
    highest-``scores`` member of each cluster is its representative.
    """
    corr = np.asarray(corr_denoised, dtype=float)
    if corr.ndim != 2 or corr.shape[0] != corr.shape[1]:
        raise ValueError(f"corr_denoised must be square, got shape {corr.shape}")
    n = corr.shape[0]
    sc = np.asarray(scores, dtype=float).ravel()
    if sc.shape != (n,):
        raise ValueError(f"scores has shape {sc.shape}, expected ({n},)")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not np.isfinite(corr).all():
        raise ValueError("corr_denoised contains NaN/inf")

    k_eff = min(k, n)
    if k_eff >= n:
        # Every asset is its own cluster — keep them all.
        selected = list(range(n))
        return SelectionResult(
            selected=selected,
            cluster_of={i: i for i in selected},
            score_of={i: float(sc[i]) for i in selected},
        )

    # Distance 1 − ρ, clamped to [0, 2], zero diagonal for squareform.
    dist = 1.0 - corr
    dist = np.clip((dist + dist.T) / 2.0, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    z = linkage(condensed, method="average")
    labels = fcluster(z, t=k_eff, criterion="maxclust")

    selected: list[int] = []
    cluster_of: dict[int, int] = {}
    score_of: dict[int, float] = {}
    for cluster_id in np.unique(labels):
        members = np.where(labels == cluster_id)[0]
        # Highest quality within the cluster; ties broken by lowest index.
        rep = int(members[np.argmax(sc[members])])
        selected.append(rep)
        cluster_of[rep] = int(cluster_id)
        score_of[rep] = float(sc[rep])
    selected.sort()
    return SelectionResult(
        selected=selected, cluster_of=cluster_of, score_of=score_of
    )
```

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_optimizer_selection.py -v` — all green.

- [ ] **5. Commit.**
  ```
  git add backend/app/optimizer/selection.py backend/tests/test_optimizer_selection.py
  git commit -m "feat(optimizer): diversification+quality selector (clustering, G5-safe score) (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T4 — Seam de dados pairwise

Novo loader T×N **sem** dropna global; `select_universe_funds` com cap opcional + teto duro `MAX_UNIVERSE_CANDIDATES`; loader de métricas de qualidade.

**Files**
- **Modify:** `backend/app/optimizer/data.py`
- **Test:** `backend/tests/test_optimizer_data_broad.py`

### Passos

- [ ] **1. Write failing test.** Crie `backend/tests/test_optimizer_data_broad.py`:

```python
"""Tests for the broad-universe data seam in app/optimizer/data.py:
- load_returns_matrix: T×N WITHOUT global dropna (NaN preserved),
- select_universe_funds: cap removed (max_assets=None) + MAX_UNIVERSE_CANDIDATES,
- load_fund_quality_metrics: Sharpe/expense/AUM per fund.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data

_FUND_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
_TODAY = dt.date(2026, 6, 11)


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


def _nav_rows(
    n: int, start: dt.date, nav0: float = 100.0
) -> list[tuple[dt.date, float, float | None]]:
    rng = np.random.default_rng(abs(hash(start)) % 2**32)
    rows = []
    nav = nav0
    day = start
    for _ in range(n):
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        r = float(rng.normal(0.0003, 0.006))
        nav *= float(np.exp(r))
        rows.append((day, nav, r))
        day += dt.timedelta(days=1)
    return rows


class _FakeSession:
    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows

    async def execute(self, stmt: Any) -> _FakeResult:
        params = stmt.compile().params
        for fund_id, rows in self._fund_rows.items():
            if fund_id in params.values():
                return _FakeResult(rows)
        return _FakeResult([])


async def test_load_returns_matrix_preserves_nan_no_global_dropna() -> None:
    """Fund A: 500 obs from 2024-01; Fund B: 500 obs from 2024-06 (younger).
    The union index keeps ALL dates; the early rows for B are NaN, not dropped.
    """
    rows_a = _nav_rows(500, dt.date(2024, 1, 2))
    rows_b = _nav_rows(500, dt.date(2024, 6, 3))
    session = _FakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    refs = [
        optimizer_data.FundAssetRef(id=_FUND_A),
        optimizer_data.FundAssetRef(id=_FUND_B),
    ]
    frame = await optimizer_data.load_returns_matrix(
        session, refs, window_days=None, today=_TODAY
    )
    # Union index is longer than the per-fund overlap (a dropna would shrink it).
    assert len(frame) > 500
    assert frame.isna().any().any()  # NaN preserved (B's early dates)
    assert list(frame.columns) == [r.label for r in refs]


async def test_load_returns_matrix_rejects_fewer_than_two() -> None:
    session = _FakeSession({_FUND_A: _nav_rows(500, dt.date(2024, 1, 2))})
    with pytest.raises(ValueError, match="at least 2"):
        await optimizer_data.load_returns_matrix(
            session, [optimizer_data.FundAssetRef(id=_FUND_A)],
            window_days=None, today=_TODAY,
        )


def test_max_universe_candidates_default_is_2000() -> None:
    assert optimizer_data.MAX_UNIVERSE_CANDIDATES == 2000
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_optimizer_data_broad.py -v` — expect `AttributeError: module 'app.optimizer.data' has no attribute 'load_returns_matrix'`.

- [ ] **3. Implement.** Em `backend/app/optimizer/data.py`:

(a) Logo abaixo de `MIN_COMMON_OBS = 400`, adicione a constante:

```python
# Hard ceiling for the on-demand broad-universe path (design §8). Above this the
# pipeline fails loud (a worker pre-compute path is phase 2, not built here).
MAX_UNIVERSE_CANDIDATES = 2000
```

(b) Adicione o novo loader logo após `load_aligned_returns` (reusa `_load_fund_returns` / `_load_equity_returns`, monta a UNIÃO de datas sem `dropna`):

```python
async def load_returns_matrix(
    session: AsyncSession,
    assets: list[AssetRef],
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    today: dt.date | None = None,
) -> pd.DataFrame:
    """T×N daily-return frame over the UNION of dates — NaN preserved.

    Stage-1 loader for the broad-universe optimizer: unlike
    ``load_aligned_returns`` (which ``dropna`` to the common-history window),
    this keeps every asset's full series and aligns on the UNION index, so a
    young fund contributes NaN before its inception instead of truncating the
    whole panel. Pairwise covariance (``app.analytics.pairwise_cov``) consumes
    the NaN directly.

    Raises ValueError (→ 422) on: fewer than 2 assets, duplicate assets, an
    unknown asset / empty window.
    """
    if len(assets) < 2:
        raise ValueError("at least 2 assets are required to optimize")
    labels = [ref.label for ref in assets]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"duplicate assets in request: {', '.join(duplicates)}")
    if window_days is not None and window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    today = today or dt.date.today()
    since = None if window_days is None else today - dt.timedelta(days=window_days)

    series: dict[str, pd.Series] = {}
    for ref in assets:
        if isinstance(ref, FundAssetRef):
            series[ref.label] = await _load_fund_returns(session, ref, since)
        else:
            series[ref.label] = await _load_equity_returns(session, ref, since)

    # Union index, NO dropna — the pairwise estimator handles the NaN mask.
    frame = pd.DataFrame(series)
    return frame
```

(c) Torne o `max_assets` de `select_universe_funds` opcional e adicione o teto duro. Altere a assinatura e o corpo:

Assinatura — troque `max_assets: int,` por:
```python
    max_assets: int | None,
```

No corpo, troque o final do `stmt` (o `.limit(max_assets)`) por uma aplicação condicional + teto. Substitua:
```python
        .order_by(order.nulls_last(), Fund.ticker.nulls_last(), Fund.instrument_id)
        .limit(max_assets)
    )
    result = await session.execute(stmt)
    return [UniverseFund(id=iid, ticker=ticker, name=name) for iid, ticker, name in result.all()]
```
por:
```python
        .order_by(order.nulls_last(), Fund.ticker.nulls_last(), Fund.instrument_id)
    )
    if max_assets is not None:
        stmt = stmt.limit(max_assets)
    else:
        # Broad-universe path: no LIMIT, but cap at the hard ceiling + 1 so we
        # can detect (and fail loud on) an over-large universe without scanning
        # the whole table.
        stmt = stmt.limit(MAX_UNIVERSE_CANDIDATES + 1)
    result = await session.execute(stmt)
    funds = [
        UniverseFund(id=iid, ticker=ticker, name=name)
        for iid, ticker, name in result.all()
    ]
    if max_assets is None and len(funds) > MAX_UNIVERSE_CANDIDATES:
        raise ValueError(
            f"universe matched more than {MAX_UNIVERSE_CANDIDATES} funds — "
            "narrow the filters (this on-demand path is capped; a pre-computed "
            "worker path is planned for larger universes)"
        )
    return funds
```

(d) Adicione o loader de métricas de qualidade (Sharpe_1y / expense_ratio / AUM) logo após `load_fund_asset_class`:

```python
async def load_fund_quality_metrics(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, float | None]]:
    """Per-fund quality signals for the Stage-1 score (G5-safe).

    Returns ``{instrument_id: {"sharpe_1y": .., "expense_ratio": .., "aum_usd":
    ..}}`` — each value ``None`` where the source lacks it. ``sharpe_1y`` comes
    from ``FundRiskLatest``; ``expense_ratio`` / ``aum_usd`` from ``Fund``. NO
    expected-return field is read (gate G5).
    """
    if not fund_ids:
        return {}
    result = await session.execute(
        select(
            Fund.instrument_id,
            Fund.expense_ratio,
            Fund.aum_usd,
            FundRiskLatest.sharpe_1y,
        )
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .where(Fund.instrument_id.in_(fund_ids))
    )
    found: dict[uuid.UUID, dict[str, float | None]] = {}
    for iid, expense, aum, sharpe in result.all():
        found[iid] = {
            "sharpe_1y": float(sharpe) if sharpe is not None else None,
            "expense_ratio": float(expense) if expense is not None else None,
            "aum_usd": float(aum) if aum is not None else None,
        }
    return {fid: found.get(fid, {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None}) for fid in fund_ids}
```

> **Nota de verificação (worker deve confirmar):** os campos `Fund.expense_ratio` e `FundRiskLatest.sharpe_1y` existem nos modelos (`app/models/fund.py`). `funds_catalog.FundFilters` já expõe `expense_ratio_max` e `sharpe_1y_min`, então os campos existem na camada de catálogo; **confirme os nomes exatos dos atributos do ORM** com um `grep` em `app/models/fund.py` antes de implementar e ajuste se diferirem (ex.: `sharpe_1y` pode estar em `FundRiskLatest` com outro nome). Se um campo não existir, omita-o do score (o `_minmax` já trata ausência como neutro).

(e) **Callers de `select_universe_funds` (VERIFICADO):** há DUAS chamadas no código — `app/services/portfolio_builder.py:300` (ajustada no T6) e `app/api/routes/correlation_regime.py:45`. Ambas passam `max_assets=spec.max_assets`, sempre um `int` (o `UniverseSpecIn.max_assets` tem default `30` e `ge=2`). Mudar o parâmetro de `int` para `int | None` é **retro-compatível** — nenhuma das duas chamadas existentes precisa mudar (a do correlation_regime permanece intacta). Só o novo caminho broad do builder passará `None`.

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_optimizer_data_broad.py tests/test_optimizer_data.py -v` — novos testes verdes e os antigos não regridem.

- [ ] **5. Commit.**
  ```
  git add backend/app/optimizer/data.py backend/tests/test_optimizer_data_broad.py
  git commit -m "feat(optimizer): broad-universe data seam — union loader, optional cap, candidate ceiling, quality metrics (T4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T5 — `sigma_robust` no engine

Estimador de covariância do Estágio 2 que escolhe RMT vs Ledoit-Wolf por `q = N/T`; sempre PSD-repair; sem mudar a interface dos `solve_*`.

**Files**
- **Modify:** `backend/app/optimizer/engine.py`
- **Test:** `backend/tests/test_optimizer_sigma_robust.py`

### Passos

- [ ] **1. Write failing test.** Crie `backend/tests/test_optimizer_sigma_robust.py`:

```python
"""Tests for engine.sigma_robust — RMT path when q=N/T>0.5, else Ledoit-Wolf;
always PSD-repaired; deterministic fallback.
"""

import numpy as np
import pytest

from app.optimizer import engine


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


def test_sigma_robust_low_q_matches_ledoit_wolf() -> None:
    """q = 5/400 = 0.0125 < 0.5 ⇒ the Ledoit-Wolf path (×252), PSD-repaired.

    sigma_robust always ends in repair_psd, so the low-q result must equal
    repair_psd(sigma_ledoit_wolf(...)) — NOT the bare LW (repair_psd may clamp
    the condition number on an ill-conditioned panel)."""
    x = _factor_returns(400, 5, seed=1)
    robust = engine.sigma_robust(x)
    lw = engine.repair_psd(engine.sigma_ledoit_wolf(x))
    np.testing.assert_allclose(robust, lw, atol=1e-10)


def test_sigma_robust_high_q_uses_rmt_path_and_is_psd() -> None:
    """q = 40/60 = 0.67 > 0.5 ⇒ RMT path; result differs from plain LW but
    stays PSD and symmetric, with the same annualization scale."""
    x = _factor_returns(60, 40, seed=2)
    robust = engine.sigma_robust(x)
    assert robust.shape == (40, 40)
    np.testing.assert_allclose(robust, robust.T, atol=1e-9)
    assert np.linalg.eigvalsh(robust).min() > -1e-9  # PSD after repair
    lw = engine.sigma_ledoit_wolf(x)
    assert not np.allclose(robust, lw)  # RMT denoise changed the estimate
    # Annualized: diagonal variances are on the ×252 scale, same order as LW.
    assert np.median(np.diag(robust)) > np.median(np.diag(lw)) * 0.1


def test_sigma_robust_threshold_is_configurable() -> None:
    """Forcing q_threshold high keeps a high-q panel on the Ledoit-Wolf path
    (compared against the PSD-repaired LW, since sigma_robust always repairs)."""
    x = _factor_returns(60, 40, seed=3)
    forced_lw = engine.sigma_robust(x, q_threshold=10.0)
    lw = engine.repair_psd(engine.sigma_ledoit_wolf(x))
    np.testing.assert_allclose(forced_lw, lw, atol=1e-10)


def test_sigma_robust_rejects_nan() -> None:
    x = _factor_returns(100, 5, seed=4)
    x[0, 0] = np.nan
    with pytest.raises(engine.OptimizerError, match="NaN"):
        engine.sigma_robust(x)
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_optimizer_sigma_robust.py -v` — expect `AttributeError: module 'app.optimizer.engine' has no attribute 'sigma_robust'`.

- [ ] **3. Implement.** Em `backend/app/optimizer/engine.py`, adicione um import de topo e a função logo após `sigma_ledoit_wolf`.

No topo, junto aos imports (`import cvxpy as cp` / `import numpy as np`), acrescente:
```python
from app.analytics import rmt
```

Logo após `sigma_ledoit_wolf` (antes de `_check_constraint_params`), adicione:

```python
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
        raise OptimizerError(f"returns matrix too small for covariance: shape={arr.shape}")
    if not np.isfinite(arr).all():
        raise OptimizerError("returns matrix contains NaN/inf — refusing to estimate covariance")

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
```

> **Nota:** `rmt.ledoit_wolf_constant_correlation` usa convenção `1/T` (não anualizada); por isso o `sigma_robust` recompõe explicitamente a variância anualizada (`std²·252`) sobre a correlação denoised, mantendo a mesma escala ×252 do `sigma_ledoit_wolf` (que o T2 do builder e o `vol_ann` de saída assumem).

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_optimizer_sigma_robust.py tests/test_optimizer_engine.py -v` — novos verdes e G2/G4/G5 não regridem.

- [ ] **5. Commit.**
  ```
  git add backend/app/optimizer/engine.py backend/tests/test_optimizer_sigma_robust.py
  git commit -m "feat(optimizer): sigma_robust — RMT cov when q=N/T>0.5, else Ledoit-Wolf, always PSD (T5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T6 — Orquestração no builder (Estágios 1+2 + diagnóstico)

Encadeia Gates 1–3 (sem cap) → `load_returns_matrix` → Estágio 1 (`robust_selection_covariance` + `select_diversified`) → `load_aligned_returns` dos K → Estágio 2 (`sigma_robust` + `solve_*`), com diagnóstico de seleção no contrato de resposta.

**Files**
- **Modify:** `backend/app/services/portfolio_builder.py`
- **Modify:** `backend/app/schemas/builder.py` (campos novos consumidos aqui; o schema completo é finalizado no T7)
- **Test:** `backend/tests/test_builder_broad_universe.py`

### Passos

- [ ] **1. Write failing test.** Crie `backend/tests/test_builder_broad_universe.py`. Stuba `select_universe_funds`, `load_returns_matrix`, `load_aligned_returns`, `load_fund_quality_metrics` no módulo canônico `app.optimizer.data`:

```python
"""End-to-end test for the broad-universe optimize path (Stage 1 + Stage 2).

Data-loading is stubbed at app.optimizer.data; the selection + engine math runs
LIVE so the happy path exercises the real two-stage pipeline.
"""

import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i + 1) for i in range(n)]


def _stub_broad(monkeypatch: pytest.MonkeyPatch, n_funds: int = 12) -> list[uuid.UUID]:
    ids = _ids(n_funds)

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        assert kw.get("max_assets") is None  # broad path removes the cap
        return [
            optimizer_data.UniverseFund(id=i, ticker=f"F{k}", name=f"Fund {k}")
            for k, i in enumerate(ids)
        ]

    async def fake_matrix(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        # 3 planted clusters of 4 funds, 600 obs, no NaN (all full history).
        rng = np.random.default_rng(5)
        cols = {}
        for c in range(3):
            common = rng.standard_normal((600, 1))
            for j in range(4):
                idio = rng.standard_normal((600, 1))
                ref = refs[c * 4 + j]
                cols[ref.label] = (0.85 * common + 0.15 * idio).ravel()
        return pd.DataFrame(cols, index=pd.bdate_range("2023-01-02", periods=600))

    async def fake_aligned(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        rng = np.random.default_rng(6)
        return pd.DataFrame(
            {r.label: rng.normal(0.0003, 0.009, 500) for r in refs},
            index=pd.bdate_range("2023-01-02", periods=500),
        )

    async def fake_quality(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        return {
            fid: {"sharpe_1y": 0.5 + 0.1 * i, "expense_ratio": 0.005, "aum_usd": 1e8}
            for i, fid in enumerate(fund_ids)
        }

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    monkeypatch.setattr(optimizer_data, "load_returns_matrix", fake_matrix)
    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_aligned)
    monkeypatch.setattr(optimizer_data, "load_fund_quality_metrics", fake_quality)
    return ids


async def test_broad_universe_returns_lean_portfolio_with_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"broad_universe": True, "max_positions": 3, "rank_by": "sharpe_1y"},
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # Lean portfolio: exactly the K selected representatives (one per cluster).
    assert len(body["weights"]) == 3
    weights = [w["weight"] for w in body["weights"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    sel = body["diagnostics"]["selection"]
    assert sel is not None
    assert sel["n_candidates"] == 12
    assert sel["n_selected"] == 3
    assert sel["excluded"] == []


async def test_broad_universe_too_small_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A universe resolving to <2 funds is a 422 (fail-loud)."""

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        return [optimizer_data.UniverseFund(id=uuid.UUID(int=1), ticker="F", name="F")]

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    payload = {"universe": {"broad_universe": True}, "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
```

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_builder_broad_universe.py -v` — expect 422/`ValidationError` (o schema ainda não tem `broad_universe`/`max_positions`, e o builder ainda não tem o caminho de dois estágios).

- [ ] **3. Implement (schema — campos consumidos aqui).** Em `backend/app/schemas/builder.py`, dentro de `UniverseSpecIn`, adicione (após `include_instrument_ids`):

```python
    broad_universe: bool = False
    """Broad-universe mode: drop the ranking LIMIT and run the two-stage
    pipeline (Stage-1 risk-structure selection → Stage-2 convex allocation) over
    the FULL filtered universe (Gates 1–3), up to ``MAX_UNIVERSE_CANDIDATES``.
    When True, ``max_assets`` is ignored and ``max_positions`` sets the final
    portfolio cardinality."""

    max_positions: Annotated[int, Field(ge=2, le=MAX_UNIVERSE_ASSETS)] = (
        DEFAULT_UNIVERSE_ASSETS
    )
    """Target cardinality K of the FINAL portfolio in broad-universe mode
    (clusters ≈ positions). Ignored in the ranked (non-broad) mode."""

    min_pair_overlap: Annotated[int, Field(ge=1)] = 252
    """Minimum per-pair overlap (trading days) for the Stage-1 pairwise
    covariance; funds below it are excluded with a structured reason."""
```

E adicione a re-exportação do diagnóstico de seleção. Após `class ViewConsistencyOut(...)`, adicione:

```python
class ExcludedFundOut(BaseModel):
    """A fund dropped by Stage-1 with its reason (fail-loud transparency)."""

    fund: str
    reason: str


class SelectionDiagnosticsOut(BaseModel):
    """Stage-1 selection summary (broad-universe mode only)."""

    n_candidates: int
    n_selected: int
    excluded: list[ExcludedFundOut]
    # selected fund label -> cluster id (which risk cluster it represents).
    clusters: dict[str, int]
```

E em `DiagnosticsOut`, adicione o campo:

```python
    # Present only on the broad-universe path.
    selection: SelectionDiagnosticsOut | None = None
```

- [ ] **4. Implement (builder orchestration).** Em `backend/app/services/portfolio_builder.py`:

(a) Imports — acrescente:
```python
from app.optimizer import selection as optimizer_selection
from app.schemas.builder import (
    ExcludedFundOut,
    SelectionDiagnosticsOut,
)
```
(adicione `ExcludedFundOut, SelectionDiagnosticsOut` ao bloco de import existente de `app.schemas.builder`).

(b) `_resolve_assets` — no ramo `universe`, passe `max_assets=None` quando `broad_universe` e devolva também o flag. Substitua a chamada `select_universe_funds(...)` por uma forma sensível ao modo:

```python
    spec = payload.universe
    broad = spec.broad_universe
    needs_bl = bool(payload.views) or payload.objective in ("bl_utility", "max_return_cvar")
    candidates = await optimizer_data.select_universe_funds(
        session,
        _filters_from_spec(spec),
        rank_by=spec.rank_by,
        rank_dir=spec.rank_dir,
        max_assets=None if broad else spec.max_assets,
        require_aum=needs_bl,
        include_ids=spec.include_instrument_ids,
        window_days=payload.window_days,
    )
```

(A guarda `len(candidates) < 2` existente permanece e cobre o caso fail-loud.) O `_resolve_assets` atual retorna `(assets, label_map)`; mantenha-o assim — o flag `broad` é relido de `payload.universe.broad_universe` em `run_optimize`.

(c) `run_optimize` — adicione, logo no início (após `assets, label_map = await _resolve_assets(...)`), o desvio para o caminho de dois estágios quando o modo é broad. Insira **antes** de `refs = [_to_data_ref(ref) for ref in assets]`:

```python
    broad = payload.universe is not None and payload.universe.broad_universe
    selection_diag: SelectionDiagnosticsOut | None = None
    if broad:
        assert payload.universe is not None
        spec = payload.universe
        all_refs = [_to_data_ref(ref) for ref in assets]
        try:
            wide = await optimizer_data.load_returns_matrix(
                session, all_refs, window_days=payload.window_days
            )
        except ValueError as exc:
            raise BuilderError(str(exc)) from exc
        wide_labels = list(wide.columns)
        # Stage-1: robust selection covariance → diversification+quality pick.
        try:
            corr, kept, excluded = optimizer_selection.robust_selection_covariance(
                wide.to_numpy(dtype=float), min_pair_overlap=spec.min_pair_overlap
            )
        except ValueError as exc:
            raise BuilderError(str(exc)) from exc
        kept_assets = [assets[i] for i in kept]
        fund_ids = [
            ref.id for ref in kept_assets if isinstance(ref, FundRefIn)
        ]
        metrics_by_id = await optimizer_data.load_fund_quality_metrics(
            session, fund_ids
        )
        metrics = [
            metrics_by_id.get(
                ref.id, {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None}
            )
            if isinstance(ref, FundRefIn)
            else {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None}
            for ref in kept_assets
        ]
        scores = optimizer_selection.quality_score(metrics)
        result = optimizer_selection.select_diversified(
            corr, scores, k=spec.max_positions
        )
        chosen_assets = [kept_assets[i] for i in result.selected]
        if len(chosen_assets) < 2:
            raise BuilderError(
                "broad-universe selection produced fewer than 2 funds — relax the "
                "filters or lower min_pair_overlap"
            )
        # Re-narrow the universe to the K chosen funds; the rest of run_optimize
        # (Stage-2) proceeds exactly as the explicit-assets path.
        assets = chosen_assets
        kept_label_of = {i: wide_labels[orig] for i, orig in enumerate(kept)}
        excluded_out = [
            ExcludedFundOut(fund=wide_labels[orig], reason=reason)
            for orig, reason in excluded.items()
        ]
        clusters = {
            _ref_key(chosen_assets[pos]): result.cluster_of[sel_idx]
            for pos, sel_idx in enumerate(result.selected)
        }
        selection_diag = SelectionDiagnosticsOut(
            n_candidates=len(wide_labels),
            n_selected=len(chosen_assets),
            excluded=excluded_out,
            clusters=clusters,
        )
```

(d) `run_optimize` — Estágio 2 usa `sigma_robust` no caminho broad. Substitua o bloco de estimação do sigma:

```python
    try:
        sigma = engine.sigma_ledoit_wolf(scenarios)
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc
```
por:
```python
    try:
        sigma = (
            engine.sigma_robust(scenarios) if broad else engine.sigma_ledoit_wolf(scenarios)
        )
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc
```

(e) `run_optimize` — injete o diagnóstico de seleção no `DiagnosticsOut` do `return`. Em `DiagnosticsOut(...)`, adicione o argumento:
```python
            selection=selection_diag,
```

> **Nota de wiring (execução assíncrona):** o design pede execução "assíncrona/job". `run_optimize` já é `async` e a rota `await`-a; o pipeline de dois estágios roda dentro do mesmo request async (sem novo job). Mantemos isso na Fase 1 — um job/worker dedicado é Fase 2 (design §9). Não introduza fila aqui.

- [ ] **5. Run, expect PASS.** `cd backend && python -m pytest tests/test_builder_broad_universe.py tests/test_builder_route.py -v` — novos verdes e a rota explícita não regride.

- [ ] **6. Commit.**
  ```
  git add backend/app/services/portfolio_builder.py backend/app/schemas/builder.py backend/tests/test_builder_broad_universe.py
  git commit -m "feat(builder): broad-universe two-stage orchestration + selection diagnostics (T6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T7 — Rota/schemas + regen de contrato

A rota já mapeia `BuilderError`→422 e chama `run_optimize`; o trabalho de schema do modo universo-amplo foi feito no T6. Este task fecha o contrato: validações de incompatibilidade do `broad_universe` e regen do `openapi.json`/`api.d.ts`.

**Files**
- **Modify:** `backend/app/schemas/builder.py` (validador de incompatibilidade)
- **Modify (gerado):** `backend/openapi.json`, `frontend/src/lib/api/api.d.ts`
- **Test:** `backend/tests/test_builder_schema.py` (acrescenta casos)

### Passos

- [ ] **1. Write failing test.** Acrescente a `backend/tests/test_builder_schema.py` (mesmo estilo dos testes de validação de `OptimizeRequest` existentes):

```python
def test_broad_universe_incompatible_with_max_return_cvar() -> None:
    import pytest
    from pydantic import ValidationError

    from app.schemas.builder import OptimizeRequest

    with pytest.raises(ValidationError, match="broad_universe"):
        OptimizeRequest.model_validate(
            {
                "universe": {"broad_universe": True},
                "objective": "max_return_cvar",
                "cvar_limit": 0.02,
            }
        )


def test_broad_universe_accepts_min_cvar_default() -> None:
    from app.schemas.builder import OptimizeRequest

    req = OptimizeRequest.model_validate(
        {"universe": {"broad_universe": True, "max_positions": 25}}
    )
    assert req.universe is not None
    assert req.universe.broad_universe is True
    assert req.universe.max_positions == 25
    assert req.objective == "min_cvar"
```

> Verifique o estilo exato de `test_builder_schema.py` antes de escrever (imports no topo do arquivo vs. dentro do teste) e alinhe-se a ele.

- [ ] **2. Run, expect FAIL.** `cd backend && python -m pytest tests/test_builder_schema.py -k broad_universe -v` — expect FAIL (sem o validador, o request com `max_return_cvar` não levanta sobre `broad_universe`).

- [ ] **3. Implement.** Em `OptimizeRequest._check_asset_source`, dentro do ramo `if self.objective == "max_return_cvar":`, adicione (junto às checagens existentes que já rejeitam `universe`):

```python
            if self.universe is not None and self.universe.broad_universe:
                raise ValueError(
                    "max_return_cvar cannot run in broad_universe mode — it needs "
                    "expected returns (Black-Litterman views on an explicit 'assets' "
                    "list); broad_universe is risk-structure-only (gate G5)"
                )
```

> O ramo `max_return_cvar` já rejeita `universe is not None` de forma geral; este reforço explícito menciona `broad_universe` para a mensagem (e cobre o caso do teste com `match="broad_universe"`). Se a checagem geral `universe is not None` já dispara antes e a mensagem não contém "broad_universe", ajuste a ordem para que a mensagem específica venha primeiro.

- [ ] **4. Run, expect PASS.** `cd backend && python -m pytest tests/test_builder_schema.py -v` — verde.

- [ ] **5. Regenerar contrato (schema de resposta mudou: `DiagnosticsOut.selection`).** Projeto usa **pnpm**, não npm. Use `make types`, ou se o frontend não tiver `node_modules`:
  ```
  cd backend && python scripts/export_openapi.py
  cd frontend && pnpm dlx openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts
  ```
  Confirme que `backend/openapi.json` e `frontend/src/lib/api/api.d.ts` foram atualizados com `SelectionDiagnosticsOut`/`ExcludedFundOut`.

- [ ] **6. Commit.**
  ```
  git add backend/app/schemas/builder.py backend/tests/test_builder_schema.py backend/openapi.json frontend/src/lib/api/api.d.ts
  git commit -m "feat(builder): broad_universe schema guard + regenerated API contract (T7)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## T8 — Gate de regressão full-suite

Garante que o port não regrediu nada (engine G2/G4/G5, RMT, builder, BL, data).

**Files**
- (nenhum novo) — só execução.

### Passos

- [ ] **1. Run full suite.**
  ```
  cd backend && python -m pytest -q
  ```
  Esperado: todos os testes do optimizer/builder/analytics verdes (incluindo os novos T1–T7). Falhas pré-existentes não relacionadas (ex.: 18 falhas de `statistics` mencionadas na memória de Highcharts; débitos de `.test.tsx` do screener) **não** são desta mudança — anote-as no relatório, não as "conserte" aqui.

- [ ] **2. Verificação de Gate G5 (estrutural).** Confirme que o teste estrutural anti-μ do engine (`tests/test_optimizer_engine.py`, seção G5) continua passando — o `sigma_robust` e a seleção não introduzem média amostral como objetivo.
  ```
  cd backend && python -m pytest tests/test_optimizer_engine.py -k g5 -v
  ```

- [ ] **3. Type-check (se o projeto rodar mypy/pyright no backend).** Rode o linter/type-checker do projeto sobre os arquivos tocados; corrija qualquer erro de tipo introduzido (assinaturas novas devem ser totalmente anotadas).

- [ ] **4. Commit (se houver ajustes do gate).**
  ```
  git add -A
  git commit -m "test(optimizer): full-suite regression gate for broad-universe port (T8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  (Se nada mudou, pule o commit — o gate é só verificação.)

---

## T9 — Restaurar a UI das métricas FI/alt no `FundProfileView.tsx` (frontend, independente)

Tarefa de **frontend pura, independente do pipeline do optimizer** (último item do plano por decisão do dono). O commit `b634ce9` removeu um bloco de "analytics por classe de fundo" (`scoring_model` → equity/fixed_income/cash/alternatives) que exibia métricas FI/cash/alt, porque eram **dead (sempre NULL)**. O Tier 3 (task T1B-8) fez o worker `risk_metrics.py` passar a calcular **4 dessas métricas**, e o backend já as serve em `FundRiskOut` (`backend/app/schemas/funds.py`, linhas ~106–109): `empirical_duration`, `credit_beta`, `inflation_beta`, `crisis_alpha_score`.

> **ESCOPO CRÍTICO — não é um revert de `b634ce9`.** O bloco removido referenciava MUITOS campos que o backend **NÃO serve hoje** (`empirical_duration_r2`, `credit_beta_r2`, `inflation_beta_r2`, `yield_proxy_12m`, `duration_adj_drawdown_1y`, e todas as métricas de `cash`: `seven_day_net_yield`, `weighted_avg_maturity_days`, `pct_weekly_liquid`, `nav_per_share_mmf`, `fed_funds_rate_at_calc`). Restaurar o bloco original referenciaria campos inexistentes no tipo `FundRiskOut` (erro de TS). **Restaure SOMENTE os 4 campos acima.** Os demais exigiriam um port adicional no worker/schema (fora deste escopo).

> **Pré-requisito de dados:** esses 4 campos são populados pelo worker SÓ para fundos FI/alt (NULL para equity). Portanto a exibição deve ser **condicional** (só renderiza o grupo quando ao menos um dos 4 é não-NULL) para não poluir a UI de fundos de equity com "—". Em produção, as colunas só ficam não-NULL após uma execução do worker de risk-metrics sobre o data-lake.

**Files**
- **Modify:** `frontend/src/components/funds/FundProfileView.tsx`

### Passos

- [ ] **1. Confirmar os campos no tipo gerado.** Verifique que `risk.empirical_duration`, `risk.credit_beta`, `risk.inflation_beta`, `risk.crisis_alpha_score` existem no tipo de `risk` (o `FundRiskOut` gerado em `frontend/src/lib/api/api.d.ts`). Se T7 regenerou o contrato, eles estarão lá (no Tier 3 já estavam). NÃO referencie nenhum campo `*_r2` / `yield_proxy_*` / cash — eles não existem no tipo.

- [ ] **2. Adicionar um grupo condicional no Card "Risk snapshot".** No `FundProfileView.tsx`, dentro do Card `title="Risk snapshot"` (atualmente por volta da linha 764), após as `StatRow` existentes, adicione um grupo renderizado só quando há dados FI/alt. Use os helpers já presentes no arquivo (`num(value, dp)` na ~linha 94; `StatRow` importado de `@/components/ui/panels`):

```tsx
{(risk.empirical_duration !== null ||
  risk.credit_beta !== null ||
  risk.inflation_beta !== null ||
  risk.crisis_alpha_score !== null) && (
  <>
    {risk.empirical_duration !== null && (
      <StatRow label="Empirical duration" value={num(risk.empirical_duration)} />
    )}
    {risk.credit_beta !== null && (
      <StatRow label="Credit beta" value={num(risk.credit_beta)} />
    )}
    {risk.inflation_beta !== null && (
      <StatRow label="Inflation beta" value={num(risk.inflation_beta)} />
    )}
    {risk.crisis_alpha_score !== null && (
      <StatRow label="Crisis alpha score" value={num(risk.crisis_alpha_score)} />
    )}
  </>
)}
```
  (Confirme o nome exato do objeto — `risk` — e o local exato do bloco de `StatRow` do "Risk snapshot" lendo o componente; insira o grupo seguindo o padrão das `StatRow` vizinhas. Se o `risk` puder ser `null`/`undefined` no escopo, proteja com o mesmo guard `risk &&` já usado pelas KPIs vizinhas.)

- [ ] **3. Type-check + build (pnpm, não npm).** Da raiz do frontend:
  ```
  cd frontend && pnpm run types && pnpm run build
  ```
  Esperado: 0 erros de tipo (os 4 campos existem no `FundRiskOut`; nenhum campo inexistente referenciado) e build OK.

- [ ] **4. Visual-check.** Rode o app (ou Storybook/preview do componente) e abra o perfil de um fundo FI/alt com métricas populadas: as 4 linhas aparecem no "Risk snapshot". Abra um fundo de equity (métricas NULL): o grupo NÃO aparece (sem linhas "—" extras). Se não houver dados não-NULL em dev, valide via um fixture/mock do `risk` com os 4 campos preenchidos.

- [ ] **5. Commit.**
  ```
  git add frontend/src/components/funds/FundProfileView.tsx
  git commit -m "feat(funds): restore FI/alt risk metrics in FundProfileView (empirical_duration/credit_beta/inflation_beta/crisis_alpha_score) (T9)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Apêndice — pontos a confirmar no código real (sinalizados ao dono)

1. **`load_fund_quality_metrics` (T4):** VERIFICADO no código real — `Fund.expense_ratio`, `Fund.aum_usd` e `FundRiskLatest.sharpe_1y` existem com EXATAMENTE esses nomes (`app/models/fund.py` L86/L90/L159, todos `Mapped[Decimal | None]`). Atenção: são `Decimal | None`, então o cast `float(...)` no loader é necessário (já está no código do T4).
2. **Escala do `sigma_robust` RMT (T5):** o `rmt.ledoit_wolf_constant_correlation` usa convenção `1/T` (não anualizada). O plano recompõe a variância anualizada (`std²·252`) sobre a correlação denoised para casar com a escala ×252 do `sigma_ledoit_wolf` (que `vol_ann` e os `solve_*` assumem). Revisar o cálculo de reescala.
3. **Validador `broad_universe` × `max_return_cvar` (T7):** o ramo existente já rejeita qualquer `universe` para `max_return_cvar`; a checagem adicional é só para a mensagem específica. Confirmar a ordem das checagens para o `match="broad_universe"` do teste.
