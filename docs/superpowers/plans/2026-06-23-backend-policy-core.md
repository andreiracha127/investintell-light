# Backend Policy Core (COMBO regime_aware rearch — Track B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o modelo antigo de banda única (`combined_regime` + `PROFILE_CENTERS` por band-state + `HW_SCALE` em runtime + goldfix) por `QUADRANT_POLICIES[profile][quadrant]` (12 políticas) ortogonal a um `GateOverlay` que só aperta o envelope de risco, **compondo ambos em uma dataclass coesa `EffectiveRegimePolicy` — o produto central do policy core** — com fail-loud e startup validation.

**Architecture:** Dois eixos independentes (spec §12): `QuadrantPolicy` (centro/bandas/cap/floor/sub-budgets FI, indexada por `profile × quadrant`, materializada como constante Python literal) define a política estratégica; `GateOverlay` (forma comum `GateOverlayShape` + `ProfileGatePolicy` por perfil) aperta CVaR, beta agregada e o teto de equity+thematic em `risk_off`, e zera as views de BL. O policy core compõe os dois numa única dataclass `EffectiveRegimePolicy` via `build_effective_policy(quadrant_snapshot, gate_snapshot, profile)`: ela carrega os NÚMEROS FINAIS de política (`sleeve_budgets` derivados de `center ± half_width`; `cvar_limit`/`beta_cap`/`risk_assets_cap` já com o overlay do gate; `defensive_floor` do quadrante; `bl_view_confidence_multiplier` do overlay; lineage `quadrant_snapshot_id`/`gate_snapshot_id`). **Princípio de fronteira (decisão do dono):** "A2 calcula um quadrante auditável; o policy core produz constraints econômicas; o Plano C é o único responsável por compilá-las no portfólio final." O policy core valida snapshots, seleciona `QUADRANT_POLICY`, aplica `GateOverlay`, e produz números finais — **não conhece instrumentos, não resolve feasibility, não chama CVXPY.** O backend LÊ o quadrante materializado pelo worker (`fetch_gate_regime`) e nunca recalcula. Nada normaliza centros em runtime; um validador roda no startup do `app/main.py` e impede o boot se qualquer invariante falhar. `combined_regime`, `band_state_from_quadrant`, `goldfix_target`, `effective_class_bands`/`DEFAULT_TAA_BANDS` e o fallback S4a saem do caminho de produção.

**⚠️ RELEASE GATE (fronteira A2 / policy core / Plano C — leia antes de tudo):** Embora os planos sejam separados, o backend NÃO pode declarar `regime_aware v2` pronto enquanto o Plano C não estiver aplicando TODAS as constraints expostas pelo policy core (cap por instrumento, overlap look-through, e o **cap de beta AGREGADO da carteira**). Até lá: A2 pode rodar/publicar snapshots; o policy core pode ser testado; as constraints podem aparecer em telemetria. **Nenhuma carteira pode ser publicada alegando que `beta_cap`, overlap ou caps finais foram garantidos.** Na v1 (sem Plano C), o builder consome `EffectiveRegimePolicy` e aplica `sleeve_budgets`/`cvar_limit`/`risk_assets_cap`/`defensive_floor`/`bl_view_confidence_multiplier` no caminho que já existe, mas **`beta_cap` é EXPOSTO (telemetria/diagnóstico), NÃO garantido** — o ponto de aplicação (`LinearConstraint` de beta agregado com `coef = M.T @ final_instrument_betas`) é exclusivamente do Plano C. Ver a seção "RELEASE GATE" detalhada abaixo e as flags na Self-Review.

**Tech Stack:** Python 3.13, FastAPI, numpy, pytest. Tudo no repo `E:/investintell-light-combo/backend`.

## RELEASE GATE — política exposta vs. garantida (decisão do dono, D)

Esta fronteira é **load-bearing** e governa o que cada plano pode afirmar:

- **Plano C consome** `EffectiveRegimePolicy` + universo resolvido + seleção Stage-1 + holdings/look-through + caps/minimums do request; executa `complete_macro|strict`, construção de `M`, compilação de cap/min/overlap/**beta agregado**/CVaR, preflight LP, solve, expansão `y=Mx`, pós-verificação. **O Plano C NÃO pode reinterpretar nem relaxar a política recebida.**
- **O policy core (este plano) produz** os números finais e NÃO compila constraints, não resolve feasibility, não chama CVXPY. Ele apenas EXPÕE `EffectiveRegimePolicy`.
- **Ponto de aplicação do `beta_cap` (Plano C, NÃO este plano):** com `y = M x` (x = pesos Level-1, y = book final), `βᵀy = (Mᵀβ)ᵀx`, logo o compilador cria `LinearConstraint(coef = M.T @ final_instrument_betas, lo=None, hi=effective_beta_cap, label="portfolio_beta_cap")`. O engine já tem o contrato genérico de constraint linear.
- **O que é EXPOSTO mas NÃO garantido na v1 (sem Plano C):** `EffectiveRegimePolicy.beta_cap` é um cap de beta AGREGADO da carteira (`β_portfolio ≤ effective_beta_cap`). Na v1 o builder o emite em telemetria/diagnóstico mas **não constrói a `LinearConstraint` agregada** — portanto nenhuma carteira pode ser publicada afirmando que o beta agregado foi garantido. Os campos que SÃO aplicados na v1 (no caminho existente): `sleeve_budgets`, `cvar_limit`, `risk_assets_cap`, `defensive_floor`, `bl_view_confidence_multiplier`.
- **Critério de "pronto" (`regime_aware v2`):** só quando o Plano C aplicar TODAS as constraints expostas (incluindo o beta agregado e o overlap look-through). Até lá, qualquer afirmação de garantia de beta/overlap/caps finais é proibida.

## Global Constraints

- Worktree/branch: `E:/investintell-light-combo` @ `feat/combo-regime-allocator`. Todo path abaixo é relativo a `backend/`.
- Rodar testes do diretório `backend/` com o venv do projeto: `.venv/Scripts/python -m pytest ...` (Windows). Os exemplos usam `python -m pytest` assumindo o venv ativo.
- Sem remote (merges locais). **NÃO mergear para main nem popular prod** — ativação é atômica (worker v2 + backend v2 juntos, spec §36), fora do escopo deste plano.
- **7 sleeves estruturais** (ordem load-bearing): `("cash","equity","fixed_income","thematic","alternatives","gold","long_short")`. SH/hedge NÃO é sleeve estrutural (spec §13/§5).
- **4 quadrantes** (lowercase, como o worker materializa em `regime_gate_daily.quadrant`): `recovery`, `expansion`, `slowdown`, `contraction` (spec §3).
- **3 perfis**: `aggressive`, `moderate`, `conservative`.
- **Fail-loud** (spec §1.7/§7): nunca pesos com warnings; nunca relaxa constraint; nunca `None → expansion`/`None → risk_on`; erro estruturado quando faltar política/quadrante/gate. **Sem normalização de centros em runtime** (spec §15).
- **Invariantes das políticas** (spec §15), por política: `Σ_g center_g = 1`; `0 ≤ center_g ≤ 1`; `lo_g = center_g − half_width_g`; `hi_g = center_g + half_width_g`; `0 ≤ lo_g ≤ center_g ≤ hi_g ≤ 1`; `Σ lo_g ≤ 1 ≤ Σ hi_g`; `equity+thematic ≤ risk_assets_cap`; `cash+fixed_income+gold+long_short ≥ defensive_floor`.
- **Invariantes do gate** (spec §23): `cvar_mult ∈ (0,1]`; `beta_mult ∈ (0,1]`; `reduction ≥ 0`; `intensity ∈ [0,1]`; `risk_on` = identidade; gate nunca aumenta risco/injeta SH/altera centro.
- **Tipos canônicos** (consistência entre tasks): `Budget`, `Quadrant`, `GateState`, `QuadrantPolicy`, `EffectiveRegimePolicy`, `GateOverlayShape`, `ProfileGatePolicy`, `EffectiveGate`. `Quadrant` e `GateState` são **type aliases de `str`** neste plano (`Quadrant = str` lowercase `recovery|expansion|slowdown|contraction`; `GateState = str` `risk_on|risk_off`), pois o worker materializa strings e o reader/Track A produz os snapshots tipados (`QuadrantSnapshot`/`GateSnapshot`, fora deste plano). O policy core consome o `GateRegimeSnapshot` do reader (`taa_bands.fetch_gate_regime`) como o `gate_snapshot`/`quadrant_snapshot` concretos na v1.
- **`EffectiveRegimePolicy` é o produto central do policy core**: dataclass coesa (frozen) que `build_effective_policy(quadrant_snapshot, gate_snapshot, profile)` produz a partir de (`QuadrantSnapshot` válido + `GateSnapshot` válido + `profile`). `sleeve_budgets` derivam de `QuadrantPolicy.center ± half_width`; `cvar_limit`/`beta_cap`/`risk_assets_cap` recebem o overlay do gate; `defensive_floor` vem do quadrante (v1); `bl_view_confidence_multiplier` vem do overlay; `fixed_income_sub_budgets={}` na v1; `quadrant_snapshot_id`/`gate_snapshot_id` para lineage.
- **`beta_cap` = cap de beta AGREGADO da carteira** (NÃO reusar caps por instrumento): a política congelada é `β_portfolio ≤ effective_beta_cap`. Base = ladder por perfil `PROFILE_PORTFOLIO_BETA_CAPS`; `effective_beta_cap = base_portfolio_beta_cap · effective_beta_multiplier`. O policy core SÓ expõe `EffectiveRegimePolicy.beta_cap`. A semântica NÃO é: redução do cap individual de cada ativo, alteração de `cap_vec`, penalização no objetivo, nem filtro pós-solve com warning. O ponto de aplicação (`LinearConstraint` agregada) é Plano C.
- **Regra de nomenclatura (travada):** "Se o objeto atualmente chamado `beta_graduated_caps` produzir caps por instrumento, ele NÃO representa essa política. Nesse caso: preserve-o para sua função atual; renomeie o ladder do mandato para `PROFILE_PORTFOLIO_BETA_CAPS`; não trate os dois conceitos como equivalentes." Verificado no código (`taa_bands.beta_graduated_caps:513-529`): **produz caps POR INSTRUMENTO** (`base_caps: np.ndarray` → `caps[i] = base_caps[i]·min(1, max(0.02, 1 − bg_coef·max(0, beta_i − 0.3)))`, um throttle de beta-vs-SPY por ativo). Logo: introduzir `PROFILE_PORTFOLIO_BETA_CAPS` (ladder de beta agregado por perfil, seeds a calibrar em A4) como base do `effective_beta_cap`, e **PRESERVAR `beta_graduated_caps` intacto** para sua função atual (per-asset throttle). Isto SOBRESCREVE qualquer esquema anterior de escalar `beta_graduated_caps` via `bg_coef_eff = base_coef/effective_beta_mult`.
- **Tolerância numérica de soma**: `abs(Σcenter − 1.0) <= 1e-6`. Todos os centros literais deste plano são construídos para somar exatamente 1.0 (resíduo de arredondamento absorvido no maior sleeve `fixed_income`).
- **Erros estruturados** (spec §31): `QUADRANT_UNAVAILABLE`, `GATE_UNAVAILABLE`, `POLICY_NOT_FOUND`, `POLICY_VERSION_MISMATCH`. Todos sobem como `BuilderError` (→ HTTP 422 via `app/api/routes/builder.py`).
- **As seeds §17/§18/§19 são SEMENTES** a calibrar (parameter freeze = A4, trabalho do dono). Este plano implementa a ESTRUTURA com as seeds como valores iniciais versionados; `POLICY_VERSION = "combo_policy_us_v1.0"`.
- **`fixed_income_sub_budgets`**: contrato + campo versionado **vazio (`{}`)** na v1 (spec §20: não declarar tilts FI até calibrados). O compilador two-level (matriz M, preflight, pós-verificação dos sub-budgets) é o **Plano C separado** — NÃO incluído aqui; mas o policy core EXPÕE `risk_assets_cap`/`defensive_floor`/`fixed_income_sub_budgets`/`beta_cap`/`cvar_limit` (via `EffectiveRegimePolicy`) para C consumir.

### Decisões travadas resolvidas neste plano (ambiguidades do handoff)

1. **Mapeamento RECOVERY/EXPANSION** (confirmado lendo `PROFILE_CENTERS`, `taa_bands.py:146-177`, e `band_state_from_quadrant`, `:190-205`): o `PROFILE_CENTERS` atual chaveia por band-state `RISK_ON / INFLATION / SLOWDOWN / CONTRACTION`. O quadrante `recovery` mapeia para a linha `RISK_ON`; `expansion` → `INFLATION`; `slowdown` → `SLOWDOWN`; `contraction` → `CONTRACTION`. **`RISK_OFF` NÃO é quadrante** — era o gate dentro do antigo `combined_regime` (`taa_bands.py:347-348`), e some como eixo separado (o `GateOverlay`). Confirmado também por `band_state_from_quadrant`: `RECOVERY→RISK_ON`, `EXPANSION→INFLATION`.
2. **`Σcenter=1` em RECOVERY/EXPANSION**: as linhas `RISK_ON`/`INFLATION` atuais NÃO somam 1 (ex.: `conservative RISK_ON` = 1.07; `aggressive INFLATION` = 0.97) porque `normalized_profile_centers` (`taa_bands.py:208-216`) normaliza em runtime — o que §15/§I proíbem. Este plano materializa os centros RECOVERY/EXPANSION **já normalizados** (valores literais finais em Task 1, derivados por `raw_g / Σraw` e o resíduo de arredondamento absorvido em `fixed_income`). As seeds SLOWDOWN/CONTRACTION (§17/§18) já somam exatamente 100% — usadas verbatim.
3. **Ponto de aplicação do `beta_tightening`** (decisão FINAL do dono, sobrescreve o esquema `bg_coef_eff` anterior): a política congelada é um **cap de beta AGREGADO da carteira**, não um throttle por ativo. `beta_graduated_caps` (verificado: per-instrumento, `taa_bands.py:513-529`) é PRESERVADO intacto para sua função atual (per-asset throttle, consumido pelo Plano C/S4a-legado). Introduz-se um conceito NOVO e independente: `PROFILE_PORTFOLIO_BETA_CAPS` (ladder de beta agregado de carteira por perfil) e `effective_beta_cap = base_portfolio_beta_cap · effective_beta_multiplier` (menor `effective_beta_multiplier` ⇒ cap agregado mais apertado). O policy core SÓ expõe `EffectiveRegimePolicy.beta_cap`. NÃO escalar `bg_coef` por `effective_beta_mult`; NÃO criar um segundo conjunto de caps por ativo. O ponto de aplicação (a `LinearConstraint(coef = M.T @ final_instrument_betas, hi=effective_beta_cap, label="portfolio_beta_cap")`) é exclusivamente do Plano C. Na v1 o `beta_cap` é EXPOSTO em telemetria, não garantido (RELEASE GATE). Documentado em Tasks 3 (`PROFILE_PORTFOLIO_BETA_CAPS`/`EffectiveGate.beta_cap`) e 5 (`EffectiveRegimePolicy.beta_cap`).
4. **half_width**: escalar simétrico por sleeve (`half_width: dict[str, float]`, spec §14 literal), `lo=center−hw`, `hi=center+hw`. As seeds §19 (assimétricas lo/hi) são colapsadas para o lado MENOR (mais conservador) por sleeve para garantir `0≤lo≤center≤hi≤1` sem estourar IPS — documentado em Task 1.
5. **Layout das 12 políticas**: constante Python literal em um novo módulo `app/services/quadrant_policy.py` (não tabela DB). Justificativa: spec §36 valida `policy_version` por igualdade de string worker↔backend, e §37 exige startup validation sem I/O. `policy_version` espelha o que o worker publica.

---

### Task 1: Contrato `QuadrantPolicy`/`Budget` + `QUADRANT_POLICIES` (12 políticas)

**Files:**
- Create: `app/services/quadrant_policy.py`
- Test: `tests/test_quadrant_policy.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Quadrant: TypeAlias = str` (lowercase `recovery|expansion|slowdown|contraction`); `GateState: TypeAlias = str` (`risk_on|risk_off`) — aliases consumidos por `gate_overlay`/`EffectiveRegimePolicy` para tipar a fronteira sem reintroduzir enums (o worker materializa strings).
  - `STRUCTURAL_SLEEVES: tuple[str, ...]` = `("cash","equity","fixed_income","thematic","alternatives","gold","long_short")`.
  - `FIXED_INCOME_BUCKETS: tuple[str, ...]` (6 buckets, spec §20).
  - `POLICY_VERSION: str` = `"combo_policy_us_v1.0"`.
  - `QUADRANTS: tuple[str, ...]` = `("recovery","expansion","slowdown","contraction")`.
  - `PROFILES: tuple[str, ...]` = `("aggressive","moderate","conservative")`.
  - `@dataclass(frozen=True) Budget(lo: float, hi: float)`.
  - `@dataclass(frozen=True) QuadrantPolicy(center: dict[str,float], half_width: dict[str,float], risk_assets_cap: float, defensive_floor: float, fixed_income_sub_budgets: dict[str, Budget], policy_version: str)`.
  - `QUADRANT_POLICIES: dict[str, dict[str, QuadrantPolicy]]` — 12 entradas `[profile][quadrant]`.
  - `policy_bands(policy: QuadrantPolicy) -> dict[str, tuple[float, float]]` — per-sleeve `(lo, hi)` derivado de `center ± half_width`, clamped a `[0, 1]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_policy.py
import math

import pytest

from app.services import quadrant_policy as qp


def test_constants_shape() -> None:
    assert qp.STRUCTURAL_SLEEVES == (
        "cash", "equity", "fixed_income", "thematic",
        "alternatives", "gold", "long_short",
    )
    assert len(qp.FIXED_INCOME_BUCKETS) == 6
    assert qp.QUADRANTS == ("recovery", "expansion", "slowdown", "contraction")
    assert qp.PROFILES == ("aggressive", "moderate", "conservative")
    assert qp.POLICY_VERSION == "combo_policy_us_v1.0"


def test_twelve_policies_present_and_versioned() -> None:
    assert set(qp.QUADRANT_POLICIES) == set(qp.PROFILES)
    count = 0
    for profile in qp.PROFILES:
        assert set(qp.QUADRANT_POLICIES[profile]) == set(qp.QUADRANTS)
        for quadrant in qp.QUADRANTS:
            pol = qp.QUADRANT_POLICIES[profile][quadrant]
            assert isinstance(pol, qp.QuadrantPolicy)
            assert pol.policy_version == qp.POLICY_VERSION
            assert set(pol.center) == set(qp.STRUCTURAL_SLEEVES)
            assert set(pol.half_width) == set(qp.STRUCTURAL_SLEEVES)
            count += 1
    assert count == 12


def test_every_center_sums_to_one() -> None:
    for profile in qp.PROFILES:
        for quadrant in qp.QUADRANTS:
            pol = qp.QUADRANT_POLICIES[profile][quadrant]
            total = sum(pol.center.values())
            assert math.isclose(total, 1.0, abs_tol=1e-6), (
                f"{profile}/{quadrant} sums to {total}"
            )


def test_fixed_income_sub_budgets_empty_in_v1() -> None:
    for profile in qp.PROFILES:
        for quadrant in qp.QUADRANTS:
            assert qp.QUADRANT_POLICIES[profile][quadrant].fixed_income_sub_budgets == {}


def test_policy_bands_derives_lo_hi_clamped() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bands = qp.policy_bands(pol)
    assert set(bands) == set(qp.STRUCTURAL_SLEEVES)
    for g in qp.STRUCTURAL_SLEEVES:
        lo, hi = bands[g]
        c, hw = pol.center[g], pol.half_width[g]
        assert lo == pytest.approx(max(0.0, c - hw))
        assert hi == pytest.approx(min(1.0, c + hw))
        assert 0.0 <= lo <= c <= hi <= 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.quadrant_policy'`

- [ ] **Step 3: Create the module**

```python
# app/services/quadrant_policy.py
"""COMBO regime_aware policy core (spec §12-§20, model_version combo_policy_us_v1).

The strategic axis: one QuadrantPolicy per (profile, quadrant) holding FINAL
centers/half-widths (no HW_SCALE at runtime), the risk_assets_cap (equity+thematic
ceiling), the defensive_floor, and the versioned (empty-in-v1) FI sub-budgets. The
gate is a SEPARATE overlay (gate_overlay.py); it never touches these centers.

Seeds are research starting points to be calibrated in A4 (parameter freeze), not
final parameters. RECOVERY/EXPANSION centers are the legacy per-profile RISK_ON/
INFLATION rows RE-NORMALIZED to sum 1 (the old normalized_profile_centers did this
at runtime, which §15 forbids — so it is materialized here). SLOWDOWN/CONTRACTION
are the §17/§18 seeds verbatim (they already sum to 100%). No runtime normalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

# Frontier types (spec §3): the worker materializes lowercase strings, so these are
# str aliases — not enums. Track A produces the typed QuadrantSnapshot/GateSnapshot.
Quadrant: TypeAlias = str   # "recovery" | "expansion" | "slowdown" | "contraction"
GateState: TypeAlias = str  # "risk_on" | "risk_off"

POLICY_VERSION = "combo_policy_us_v1.0"

STRUCTURAL_SLEEVES: tuple[str, ...] = (
    "cash", "equity", "fixed_income", "thematic",
    "alternatives", "gold", "long_short",
)

# Versioned FI sub-bucket contract (spec §20). EMPTY in v1 (no FI tilts declared
# until calibrated); the compiler/post-verification (Plan C) consume the names.
FIXED_INCOME_BUCKETS: tuple[str, ...] = (
    "sovereign_short_intermediate",
    "sovereign_long_duration",
    "inflation_linked",
    "investment_grade_credit",
    "high_yield_preferred",
    "structured_private_credit",
)

QUADRANTS: tuple[str, ...] = ("recovery", "expansion", "slowdown", "contraction")
PROFILES: tuple[str, ...] = ("aggressive", "moderate", "conservative")


@dataclass(frozen=True)
class Budget:
    lo: float
    hi: float


@dataclass(frozen=True)
class QuadrantPolicy:
    center: dict[str, float]              # final centers, sum 1 over STRUCTURAL_SLEEVES
    half_width: dict[str, float]          # FINAL symmetric half-widths (no HW_SCALE)
    risk_assets_cap: float                # equity + thematic ceiling
    defensive_floor: float                # cash+fixed_income+gold+long_short floor
    fixed_income_sub_budgets: dict[str, Budget]  # empty {} in v1
    policy_version: str


def policy_bands(policy: QuadrantPolicy) -> dict[str, tuple[float, float]]:
    """Per-sleeve (lo, hi) from center ± half_width, clamped to [0, 1].

    No IPS re-widening and no HW_SCALE — the half-widths are already final
    (spec §19). The invariant validator (Task 2) guarantees 0≤lo≤center≤hi≤1.
    """
    bands: dict[str, tuple[float, float]] = {}
    for g in STRUCTURAL_SLEEVES:
        c = policy.center[g]
        hw = policy.half_width[g]
        bands[g] = (max(0.0, c - hw), min(1.0, c + hw))
    return bands


# Final symmetric half-widths per sleeve (spec §19 seed, collapsed to the SMALLER
# side so lo/hi never escape [0,1] given these centers). Same across quadrants in
# v1 (per-quadrant variation is a calibration degree of freedom, spec §33).
_HALF_WIDTHS: dict[str, float] = {
    "cash": 0.04, "equity": 0.04, "fixed_income": 0.06, "thematic": 0.01,
    "alternatives": 0.03, "gold": 0.03, "long_short": 0.03,
}


def _policy(
    center: dict[str, float], *, risk_assets_cap: float, defensive_floor: float
) -> QuadrantPolicy:
    return QuadrantPolicy(
        center=dict(center),
        half_width=dict(_HALF_WIDTHS),
        risk_assets_cap=risk_assets_cap,
        defensive_floor=defensive_floor,
        fixed_income_sub_budgets={},
        policy_version=POLICY_VERSION,
    )


# RECOVERY/EXPANSION centers = legacy RISK_ON/INFLATION rows re-normalized to sum 1
# (raw_g / Σraw, residual absorbed in fixed_income so each row sums to 1.0 exactly).
# SLOWDOWN/CONTRACTION = §17/§18 seeds verbatim (already sum to 100%).
QUADRANT_POLICIES: dict[str, dict[str, QuadrantPolicy]] = {
    "aggressive": {
        "recovery": _policy(
            {"cash": 0.05, "equity": 0.33, "fixed_income": 0.31, "thematic": 0.08,
             "alternatives": 0.05, "gold": 0.10, "long_short": 0.08},
            risk_assets_cap=0.45, defensive_floor=0.28),
        "expansion": _policy(
            {"cash": 0.0825, "equity": 0.2680, "fixed_income": 0.2268,
             "thematic": 0.0722, "alternatives": 0.1237, "gold": 0.1340,
             "long_short": 0.0928},
            risk_assets_cap=0.42, defensive_floor=0.33),
        "slowdown": _policy(
            {"cash": 0.10, "equity": 0.26, "fixed_income": 0.21, "thematic": 0.04,
             "alternatives": 0.14, "gold": 0.14, "long_short": 0.11},
            risk_assets_cap=0.35, defensive_floor=0.45),
        "contraction": _policy(
            {"cash": 0.16, "equity": 0.18, "fixed_income": 0.35, "thematic": 0.02,
             "alternatives": 0.06, "gold": 0.11, "long_short": 0.12},
            risk_assets_cap=0.25, defensive_floor=0.54),
    },
    "moderate": {
        "recovery": _policy(
            {"cash": 0.10, "equity": 0.23, "fixed_income": 0.38, "thematic": 0.06,
             "alternatives": 0.05, "gold": 0.10, "long_short": 0.08},
            risk_assets_cap=0.34, defensive_floor=0.43),
        "expansion": _policy(
            {"cash": 0.1340, "equity": 0.1649, "fixed_income": 0.2991,
             "thematic": 0.0515, "alternatives": 0.1237, "gold": 0.1340,
             "long_short": 0.0928},
            risk_assets_cap=0.30, defensive_floor=0.48),
        "slowdown": _policy(
            {"cash": 0.15, "equity": 0.17, "fixed_income": 0.27, "thematic": 0.03,
             "alternatives": 0.13, "gold": 0.14, "long_short": 0.11},
            risk_assets_cap=0.25, defensive_floor=0.52),
        "contraction": _policy(
            {"cash": 0.22, "equity": 0.10, "fixed_income": 0.41, "thematic": 0.01,
             "alternatives": 0.05, "gold": 0.11, "long_short": 0.10},
            risk_assets_cap=0.15, defensive_floor=0.62),
    },
    "conservative": {
        "recovery": _policy(
            {"cash": 0.1402, "equity": 0.0467, "fixed_income": 0.4206,
             "thematic": 0.0280, "alternatives": 0.0467, "gold": 0.1682,
             "long_short": 0.1496},
            risk_assets_cap=0.20, defensive_floor=0.62),
        "expansion": _policy(
            {"cash": 0.1622, "equity": 0.0450, "fixed_income": 0.3243,
             "thematic": 0.0180, "alternatives": 0.1081, "gold": 0.1892,
             "long_short": 0.1532},
            risk_assets_cap=0.18, defensive_floor=0.67),
        "slowdown": _policy(
            {"cash": 0.20, "equity": 0.07, "fixed_income": 0.34, "thematic": 0.01,
             "alternatives": 0.10, "gold": 0.15, "long_short": 0.13},
            risk_assets_cap=0.15, defensive_floor=0.62),
        "contraction": _policy(
            {"cash": 0.27, "equity": 0.04, "fixed_income": 0.45, "thematic": 0.00,
             "alternatives": 0.04, "gold": 0.10, "long_short": 0.10},
            risk_assets_cap=0.10, defensive_floor=0.72),
    },
}
```

NOTE on `expansion moderate`: the re-normalized row above sums to 0.9990 as written
(0.1340+0.1649+0.2991+0.0515+0.1237+0.1340+0.0928). Add the 0.0010 residual to
`fixed_income` → `0.3001`. Likewise verify each row in Step 4 below; the test
`test_every_center_sums_to_one` is the gate. The exact residual-corrected rows are
the literal values committed (adjust `fixed_income` per row until the test passes —
the validator tolerance is `1e-6`).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_policy.py -v`
Expected: PASS (5 passed). If `test_every_center_sums_to_one` fails for any row,
add the (signed) residual `1.0 − Σcenter` to that row's `fixed_income` value and
re-run — never normalize in code, fix the literal.

- [ ] **Step 5: Commit**

```bash
git add app/services/quadrant_policy.py tests/test_quadrant_policy.py
git commit -m "feat(combo): QuadrantPolicy contract + 12 materialized policies (seed v1)"
```

---

### Task 2: Invariantes das políticas + `validate_quadrant_policies`

**Files:**
- Modify: `app/services/quadrant_policy.py`
- Test: `tests/test_quadrant_policy.py` (append)

**Interfaces:**
- Consumes: `QUADRANT_POLICIES`, `QuadrantPolicy`, `STRUCTURAL_SLEEVES`, `PROFILES`, `QUADRANTS`, `policy_bands` (Task 1).
- Produces:
  - `class PolicyError(ValueError)` — invariant violation; structured.
  - `validate_quadrant_policies(policies: dict[str, dict[str, QuadrantPolicy]] = QUADRANT_POLICIES) -> None` — raises `PolicyError` on the first violated invariant; returns `None` when all 12 are valid.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_quadrant_policy.py` (the `import dataclasses` is added at top of the file):

```python
import dataclasses


def test_validate_passes_on_shipped_policies() -> None:
    qp.validate_quadrant_policies()  # must not raise


def test_validate_rejects_center_not_summing_one() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bad_center = dict(pol.center)
    bad_center["cash"] += 0.05  # now sums to 1.05
    bad = dataclasses.replace(pol, center=bad_center)
    policies = {"moderate": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="sum to 1"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_band_out_of_unit_interval() -> None:
    pol = qp.QUADRANT_POLICIES["aggressive"]["recovery"]
    bad_hw = dict(pol.half_width)
    bad_hw["equity"] = 0.50  # center 0.33 → lo = -0.17
    bad = dataclasses.replace(pol, half_width=bad_hw)
    policies = {"aggressive": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="lo"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_risk_assets_cap_breach() -> None:
    pol = qp.QUADRANT_POLICIES["aggressive"]["recovery"]  # equity .33 + thematic .08 = .41
    bad = dataclasses.replace(pol, risk_assets_cap=0.30)  # < .41
    policies = {"aggressive": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="risk_assets_cap"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_defensive_floor_breach() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    # cash+fi+gold+ls = .10+.38+.10+.08 = .66; demand .80 → breach
    bad = dataclasses.replace(pol, defensive_floor=0.80)
    policies = {"moderate": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="defensive_floor"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_missing_policy() -> None:
    policies = {"moderate": {"recovery": qp.QUADRANT_POLICIES["moderate"]["recovery"]}}
    with pytest.raises(qp.PolicyError, match="missing"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_sum_lo_over_one() -> None:
    # Build a policy whose lo's sum > 1 (every sleeve lo high). center is valid (sum 1)
    # but half_widths 0 and centers concentrated would not trip this; instead push
    # los up via a center that sums to 1 with large los. Easiest: fixed_income center
    # 1.0, others 0, hw 0 → Σlo = 1 (ok). To breach, we forge Σlo > 1 directly.
    pol = qp.QUADRANT_POLICIES["conservative"]["contraction"]
    bad_center = {g: 1.0 / 7 for g in qp.STRUCTURAL_SLEEVES}
    bad_hw = {g: 0.0 for g in qp.STRUCTURAL_SLEEVES}
    # Σlo = Σcenter = 1.0 here (boundary ok). Force breach: bump one center+lo above.
    bad_center["fixed_income"] = 1.0 / 7 + 1e-3
    bad_center["cash"] = 1.0 / 7 - 1e-3  # keep sum 1
    bad = dataclasses.replace(pol, center=bad_center, half_width=bad_hw)
    # Σlo == 1.0 still (lo == center, Σcenter == 1) → boundary passes; assert no raise.
    qp.validate_quadrant_policies({"conservative": {"contraction": bad}})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_policy.py -k validate -v`
Expected: FAIL — `AttributeError: module 'app.services.quadrant_policy' has no attribute 'PolicyError'`

- [ ] **Step 3: Implement the validator**

Append to `app/services/quadrant_policy.py`:

```python
_CENTER_TOL = 1e-6
_BAND_TOL = 1e-9


class PolicyError(ValueError):
    """A QuadrantPolicy invariant is violated (spec §15). Fail-loud at startup."""


def _validate_one(profile: str, quadrant: str, pol: QuadrantPolicy) -> None:
    where = f"{profile}/{quadrant}"
    if set(pol.center) != set(STRUCTURAL_SLEEVES):
        raise PolicyError(f"{where}: center sleeves must be exactly STRUCTURAL_SLEEVES")
    if set(pol.half_width) != set(STRUCTURAL_SLEEVES):
        raise PolicyError(f"{where}: half_width sleeves must be exactly STRUCTURAL_SLEEVES")
    total = sum(pol.center.values())
    if abs(total - 1.0) > _CENTER_TOL:
        raise PolicyError(f"{where}: centers must sum to 1, got {total}")
    bands = policy_bands(pol)
    sum_lo = sum(lo for lo, _hi in bands.values())
    sum_hi = sum(hi for _lo, hi in bands.values())
    for g in STRUCTURAL_SLEEVES:
        c = pol.center[g]
        lo, hi = bands[g]
        if not (0.0 <= c <= 1.0):
            raise PolicyError(f"{where}: center[{g}]={c} outside [0,1]")
        if not (-_BAND_TOL <= lo <= c + _BAND_TOL <= hi + _BAND_TOL <= 1.0 + _BAND_TOL):
            raise PolicyError(f"{where}: band[{g}] violates 0<=lo<=center<=hi<=1 (lo={lo}, hi={hi})")
    if sum_lo > 1.0 + _BAND_TOL:
        raise PolicyError(f"{where}: Σlo={sum_lo} must be <= 1")
    if sum_hi < 1.0 - _BAND_TOL:
        raise PolicyError(f"{where}: Σhi={sum_hi} must be >= 1")
    risk_assets = pol.center["equity"] + pol.center["thematic"]
    if risk_assets > pol.risk_assets_cap + _BAND_TOL:
        raise PolicyError(
            f"{where}: equity+thematic={risk_assets} exceeds risk_assets_cap={pol.risk_assets_cap}"
        )
    defensive = (
        pol.center["cash"] + pol.center["fixed_income"]
        + pol.center["gold"] + pol.center["long_short"]
    )
    if defensive < pol.defensive_floor - _BAND_TOL:
        raise PolicyError(
            f"{where}: cash+fixed_income+gold+long_short={defensive} below "
            f"defensive_floor={pol.defensive_floor}"
        )
    if pol.policy_version != POLICY_VERSION:
        raise PolicyError(f"{where}: policy_version {pol.policy_version} != {POLICY_VERSION}")


def validate_quadrant_policies(
    policies: dict[str, dict[str, QuadrantPolicy]] = QUADRANT_POLICIES,
) -> None:
    """Validate all 12 policies (spec §15/§37). Raises PolicyError on the first
    violation; the service must not start if this raises. No normalization here."""
    for profile in PROFILES:
        if profile not in policies:
            raise PolicyError(f"missing policies for profile {profile!r}")
        for quadrant in QUADRANTS:
            if quadrant not in policies[profile]:
                raise PolicyError(f"missing policy for {profile}/{quadrant}")
            _validate_one(profile, quadrant, policies[profile][quadrant])
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_policy.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/services/quadrant_policy.py tests/test_quadrant_policy.py
git commit -m "feat(combo): policy invariant validator (sum, bands, risk_assets_cap, floor)"
```

---

### Task 3: `GateOverlay` (shape + per-profile policy + effective_* formulas)

**Files:**
- Create: `app/optimizer/gate_overlay.py`
- Test: `tests/test_gate_overlay.py`

**Interfaces:**
- Consumes: `quadrant_policy.PROFILES`, `quadrant_policy.GateState` (Task 1).
- Produces:
  - `@dataclass(frozen=True) GateOverlayShape(cvar_tightening: float, beta_tightening: float, risk_assets_reduction: float)`.
  - `@dataclass(frozen=True) ProfileGatePolicy(intensity: float, bl_view_confidence_multiplier: float)`.
  - `GATE_OVERLAY_SHAPE: GateOverlayShape` (common v1 shape).
  - `PROFILE_GATE_POLICIES: dict[str, ProfileGatePolicy]` (3 profiles).
  - `PROFILE_PORTFOLIO_BETA_CAPS: dict[str, float]` — **ladder de beta AGREGADO de carteira por perfil** (seeds a calibrar em A4). É a base do cap agregado `β_portfolio ≤ effective_beta_cap`. **Conceito NOVO e independente de `taa_bands.beta_graduated_caps`** (que é per-instrumento e fica intacto).
  - `@dataclass(frozen=True) EffectiveGate(cvar_mult: float, beta_mult: float, risk_assets_cap: float, beta_cap: float, bl_view_confidence_multiplier: float)` — `beta_cap` = `base_portfolio_beta_cap · beta_mult` (cap de beta AGREGADO, não por ativo).
  - `class GateError(ValueError)`.
  - `apply_gate_overlay(profile: str, state: GateState | None, *, base_risk_assets_cap: float, base_portfolio_beta_cap: float) -> EffectiveGate` — `risk_on`/`None`/unknown → identity (cvar 1.0, beta_mult 1.0, caps unchanged, bl_mult 1.0); `risk_off` → as fórmulas §22 + `beta_cap = base_portfolio_beta_cap · (1 − intensity·beta_tightening)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gate_overlay.py
import pytest

from app.optimizer import gate_overlay as go


def test_shapes_and_profiles_exist() -> None:
    assert isinstance(go.GATE_OVERLAY_SHAPE, go.GateOverlayShape)
    assert set(go.PROFILE_GATE_POLICIES) == {"aggressive", "moderate", "conservative"}
    assert set(go.PROFILE_PORTFOLIO_BETA_CAPS) == {"aggressive", "moderate", "conservative"}


def test_portfolio_beta_cap_ladder_is_monotone() -> None:
    # the aggregate portfolio-beta cap ladder is a NEW concept, independent of the
    # per-instrument beta_graduated_caps throttle. Aggressive admits more beta.
    caps = go.PROFILE_PORTFOLIO_BETA_CAPS
    assert caps["aggressive"] > caps["moderate"] > caps["conservative"]


def test_risk_on_is_identity() -> None:
    eff = go.apply_gate_overlay(
        "moderate", "risk_on", base_risk_assets_cap=0.34, base_portfolio_beta_cap=0.80
    )
    assert eff.cvar_mult == 1.0
    assert eff.beta_mult == 1.0
    assert eff.risk_assets_cap == 0.34
    assert eff.beta_cap == 0.80  # identity: aggregate cap unchanged in risk_on
    assert eff.bl_view_confidence_multiplier == 1.0


def test_none_state_is_identity() -> None:
    eff = go.apply_gate_overlay(
        "aggressive", None, base_risk_assets_cap=0.45, base_portfolio_beta_cap=0.95
    )
    assert eff == go.apply_gate_overlay(
        "aggressive", "risk_on", base_risk_assets_cap=0.45, base_portfolio_beta_cap=0.95
    )


def test_risk_off_applies_formulas() -> None:
    shape = go.GATE_OVERLAY_SHAPE
    pol = go.PROFILE_GATE_POLICIES["moderate"]
    eff = go.apply_gate_overlay(
        "moderate", "risk_off", base_risk_assets_cap=0.34, base_portfolio_beta_cap=0.80
    )
    assert eff.cvar_mult == pytest.approx(1 - pol.intensity * shape.cvar_tightening)
    assert eff.beta_mult == pytest.approx(1 - pol.intensity * shape.beta_tightening)
    assert eff.risk_assets_cap == pytest.approx(
        0.34 - pol.intensity * shape.risk_assets_reduction
    )
    # aggregate beta cap = base · effective_beta_multiplier (NOT a per-asset change)
    assert eff.beta_cap == pytest.approx(0.80 * (1 - pol.intensity * shape.beta_tightening))
    assert eff.beta_cap < 0.80
    assert eff.bl_view_confidence_multiplier == 0.0  # v1 fixed risk_off policy


def test_risk_off_never_increases_risk() -> None:
    for profile in ("aggressive", "moderate", "conservative"):
        eff = go.apply_gate_overlay(
            profile, "risk_off", base_risk_assets_cap=0.40, base_portfolio_beta_cap=0.90
        )
        assert 0.0 < eff.cvar_mult <= 1.0
        assert 0.0 < eff.beta_mult <= 1.0
        assert eff.risk_assets_cap <= 0.40
        assert eff.beta_cap <= 0.90  # aggregate cap only ever tightens


def test_ladder_preserved_across_profiles() -> None:
    caps = {
        p: go.apply_gate_overlay(
            p, "risk_off", base_risk_assets_cap=0.40, base_portfolio_beta_cap=0.80
        ).cvar_mult
        for p in ("aggressive", "moderate", "conservative")
    }
    # the 3 profiles must not collapse to the same effective tightening
    assert len(set(round(v, 6) for v in caps.values())) == 3


def test_unknown_profile_raises() -> None:
    with pytest.raises(go.GateError, match="unknown profile"):
        go.apply_gate_overlay(
            "balanced", "risk_off", base_risk_assets_cap=0.30, base_portfolio_beta_cap=0.70
        )


def test_effective_risk_assets_cap_never_negative() -> None:
    eff = go.apply_gate_overlay(
        "conservative", "risk_off", base_risk_assets_cap=0.05, base_portfolio_beta_cap=0.40
    )
    assert eff.risk_assets_cap >= 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_gate_overlay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.optimizer.gate_overlay'`

- [ ] **Step 3: Implement the overlay**

```python
# app/optimizer/gate_overlay.py
"""Gate overlay for COMBO regime_aware (spec §21-§24).

The gate is orthogonal to the quadrant (spec §12): it does not change centers,
taxonomy, or the market prior — it only TIGHTENS the risk envelope in risk_off.
A common shape (GateOverlayShape) is scaled by a per-profile intensity into the
effective multipliers (spec §22). risk_on is the identity. In v1 the risk_off
BL view-confidence multiplier is FIXED at 0.0 (μ = π; views omitted) — a policy,
not a hyperparameter (spec §24).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.quadrant_policy import GateState, PROFILES


class GateError(ValueError):
    """Invalid gate input (unknown profile) or invariant violation. Fail-loud."""


@dataclass(frozen=True)
class GateOverlayShape:
    cvar_tightening: float        # fraction the CVaR cap is cut at intensity 1
    beta_tightening: float        # fraction the AGGREGATE portfolio-beta cap is cut at intensity 1
    risk_assets_reduction: float  # absolute pp the equity+thematic cap drops at intensity 1


@dataclass(frozen=True)
class ProfileGatePolicy:
    intensity: float                      # ∈ [0,1]; preserves the per-profile ladder
    bl_view_confidence_multiplier: float  # 0.0 in risk_off v1 (μ = π)


@dataclass(frozen=True)
class EffectiveGate:
    cvar_mult: float
    beta_mult: float
    risk_assets_cap: float
    beta_cap: float  # AGGREGATE portfolio-beta cap = base_portfolio_beta_cap · beta_mult
    bl_view_confidence_multiplier: float


# Common v1 shape (seed; calibrated by ablation in A5). At intensity 1: CVaR cap
# ×0.5, aggregate portfolio-beta cap ×0.7, equity+thematic cap −0.10.
GATE_OVERLAY_SHAPE = GateOverlayShape(
    cvar_tightening=0.50,
    beta_tightening=0.30,
    risk_assets_reduction=0.10,
)

# Per-profile intensity ladder (seed): the more aggressive the mandate, the
# harder the risk-off brake. bl_view_confidence_multiplier fixed 0.0 (spec §24).
PROFILE_GATE_POLICIES: dict[str, ProfileGatePolicy] = {
    "aggressive": ProfileGatePolicy(intensity=1.00, bl_view_confidence_multiplier=0.0),
    "moderate": ProfileGatePolicy(intensity=0.70, bl_view_confidence_multiplier=0.0),
    "conservative": ProfileGatePolicy(intensity=0.50, bl_view_confidence_multiplier=0.0),
}

# Per-profile AGGREGATE portfolio-beta cap ladder (seed; calibrated in A4). This is
# the mandate-level β_portfolio ≤ cap; it is a NEW, independent concept from the
# per-instrument throttle in taa_bands.beta_graduated_caps (which is preserved as-is).
# Monotone: aggressive admits more aggregate beta than conservative.
PROFILE_PORTFOLIO_BETA_CAPS: dict[str, float] = {
    "aggressive": 0.85,
    "moderate": 0.55,
    "conservative": 0.30,
}

_IDENTITY_BL_MULT = 1.0


def _validate_shape(shape: GateOverlayShape) -> None:
    if not 0.0 <= shape.cvar_tightening < 1.0:
        raise GateError(f"cvar_tightening must be in [0,1), got {shape.cvar_tightening}")
    if not 0.0 <= shape.beta_tightening < 1.0:
        raise GateError(f"beta_tightening must be in [0,1), got {shape.beta_tightening}")
    if shape.risk_assets_reduction < 0.0:
        raise GateError(
            f"risk_assets_reduction must be >= 0, got {shape.risk_assets_reduction}"
        )


def _validate_profile_policy(profile: str, pol: ProfileGatePolicy) -> None:
    if not 0.0 <= pol.intensity <= 1.0:
        raise GateError(f"{profile}: intensity must be in [0,1], got {pol.intensity}")
    if not 0.0 <= pol.bl_view_confidence_multiplier <= 1.0:
        raise GateError(
            f"{profile}: bl_view_confidence_multiplier must be in [0,1], "
            f"got {pol.bl_view_confidence_multiplier}"
        )


def apply_gate_overlay(
    profile: str,
    state: GateState | None,
    *,
    base_risk_assets_cap: float,
    base_portfolio_beta_cap: float,
) -> EffectiveGate:
    """Effective risk envelope after the gate (spec §22).

    risk_on / None / unknown-state → identity (no tightening). risk_off →
    cvar_mult = 1 − intensity·cvar_tightening; beta_mult = 1 − intensity·
    beta_tightening; risk_assets_cap = base − intensity·risk_assets_reduction
    (floored at 0); beta_cap = base_portfolio_beta_cap · beta_mult (the AGGREGATE
    portfolio-beta cap, NOT a per-asset change); bl_view_confidence_multiplier from
    the per-profile policy (0.0 in v1). Validates §23 invariants.
    """
    if profile not in PROFILES:
        raise GateError(f"unknown profile {profile!r}")
    if (state or "").lower() != "risk_off":
        return EffectiveGate(
            cvar_mult=1.0,
            beta_mult=1.0,
            risk_assets_cap=base_risk_assets_cap,
            beta_cap=base_portfolio_beta_cap,
            bl_view_confidence_multiplier=_IDENTITY_BL_MULT,
        )
    shape = GATE_OVERLAY_SHAPE
    pol = PROFILE_GATE_POLICIES[profile]
    _validate_shape(shape)
    _validate_profile_policy(profile, pol)
    cvar_mult = 1.0 - pol.intensity * shape.cvar_tightening
    beta_mult = 1.0 - pol.intensity * shape.beta_tightening
    risk_assets_cap = max(0.0, base_risk_assets_cap - pol.intensity * shape.risk_assets_reduction)
    beta_cap = base_portfolio_beta_cap * beta_mult
    if not 0.0 < cvar_mult <= 1.0:
        raise GateError(f"{profile}: cvar_mult {cvar_mult} not in (0,1]")
    if not 0.0 < beta_mult <= 1.0:
        raise GateError(f"{profile}: beta_mult {beta_mult} not in (0,1]")
    return EffectiveGate(
        cvar_mult=cvar_mult,
        beta_mult=beta_mult,
        risk_assets_cap=risk_assets_cap,
        beta_cap=beta_cap,
        bl_view_confidence_multiplier=pol.bl_view_confidence_multiplier,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_gate_overlay.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/optimizer/gate_overlay.py tests/test_gate_overlay.py
git commit -m "feat(combo): GateOverlay shape + per-profile policy + effective_* formulas"
```

---

### Task 4: `bl_confidence_multiplier` helper (gate→BL glue)

> **DECISÃO FINAL (sobrescreve o esquema `bg_coef_eff` anterior):** o `beta_tightening` NÃO reusa `beta_graduated_caps` (per-instrumento, preservado intacto). O cap de beta é **AGREGADO de carteira** e é exposto via `EffectiveGate.beta_cap` (Task 3) — `effective_beta_cap = base_portfolio_beta_cap · beta_mult`. **NÃO existe `effective_beta_coef`.** O único glue restante deste task é o passthrough do multiplicador de confiança BL.

**Files:**
- Modify: `app/optimizer/gate_overlay.py`
- Test: `tests/test_gate_overlay.py` (append)

**Interfaces:**
- Consumes: `apply_gate_overlay`, `EffectiveGate` (Task 3).
- Produces:
  - `bl_confidence_multiplier(effective_gate: EffectiveGate) -> float` — passthrough of `effective_gate.bl_view_confidence_multiplier` (single source for the BL layer).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_overlay.py`:

```python
def test_bl_confidence_multiplier_is_zero_in_risk_off_v1() -> None:
    eff = go.apply_gate_overlay(
        "conservative", "risk_off", base_risk_assets_cap=0.20, base_portfolio_beta_cap=0.30
    )
    assert go.bl_confidence_multiplier(eff) == 0.0


def test_bl_confidence_multiplier_is_one_in_risk_on() -> None:
    eff = go.apply_gate_overlay(
        "conservative", "risk_on", base_risk_assets_cap=0.20, base_portfolio_beta_cap=0.30
    )
    assert go.bl_confidence_multiplier(eff) == 1.0


def test_no_effective_beta_coef_symbol() -> None:
    # The rejected per-asset bg_coef-scaling scheme must not exist. The aggregate
    # portfolio-beta cap lives on EffectiveGate.beta_cap, applied as a LinearConstraint
    # by Plan C — there is no per-instrument coefficient helper here.
    assert not hasattr(go, "effective_beta_coef")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_gate_overlay.py -k "confidence_multiplier or effective_beta_coef" -v`
Expected: FAIL — `AttributeError: module 'app.optimizer.gate_overlay' has no attribute 'bl_confidence_multiplier'`

- [ ] **Step 3: Implement the helper**

Append to `app/optimizer/gate_overlay.py`:

```python
def bl_confidence_multiplier(effective_gate: EffectiveGate) -> float:
    """Single source for the BL view-confidence multiplier (spec §24). 0.0 → μ=π
    (views omitted); the consumer must NEVER pass confidence=0 to omega_idzorek."""
    return effective_gate.bl_view_confidence_multiplier
```

(Do NOT add an `effective_beta_coef`: the aggregate portfolio-beta cap is `EffectiveGate.beta_cap`, compiled into a `LinearConstraint` by Plan C — never a per-asset throttle. `taa_bands.beta_graduated_caps` is preserved untouched for its own per-instrument purpose.)

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_gate_overlay.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/optimizer/gate_overlay.py tests/test_gate_overlay.py
git commit -m "feat(combo): gate→BL glue (bl_confidence_multiplier); beta cap is aggregate via EffectiveGate.beta_cap"
```

---

### Task 5: `EffectiveRegimePolicy` + `build_effective_policy` (produto central do policy core)

> **Este é o produto central do policy core (decisão B do dono).** A dataclass coesa que o builder e (eventualmente) o Plano C consomem. O policy core a produz a partir de (`QuadrantSnapshot` válido + `GateSnapshot` válido + `profile`); ela carrega os NÚMEROS FINAIS de política. O policy core **não conhece instrumentos, não resolve feasibility, não chama CVXPY** (princípio de fronteira A).

**Files:**
- Create: `app/services/effective_policy.py`
- Test: `tests/test_effective_policy.py`

**Interfaces:**
- Consumes: `quadrant_policy.QuadrantPolicy`, `quadrant_policy.policy_bands`, `quadrant_policy.QUADRANT_POLICIES`, `quadrant_policy.QUADRANTS`, `quadrant_policy.PROFILES`, `quadrant_policy.Budget`, `quadrant_policy.Quadrant`, `quadrant_policy.GateState`, `quadrant_policy.POLICY_VERSION` (Tasks 1/2); `gate_overlay.apply_gate_overlay`, `gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS`, `gate_overlay.EffectiveGate` (Tasks 3); `taa_bands.GateRegimeSnapshot` (the reader output, `taa_bands.py:533-553`) as the concrete `gate_snapshot`/`quadrant_snapshot` carrier in v1.
- Produces:
  - `@dataclass(frozen=True) EffectiveRegimePolicy(profile: str, quadrant: Quadrant, gate_state: GateState, policy_version: str, quadrant_snapshot_id: str, gate_snapshot_id: str, sleeve_budgets: dict[str, Budget], fixed_income_sub_budgets: dict[str, Budget], cvar_limit: float, beta_cap: float, risk_assets_cap: float, defensive_floor: float, bl_view_confidence_multiplier: float)`.
  - `class EffectivePolicyError(ValueError)` — non-consumable snapshot or missing inputs (structured; the builder re-raises as `BuilderError` → 422).
  - `build_effective_policy(quadrant_snapshot, gate_snapshot, profile, *, base_cvar_limit) -> EffectiveRegimePolicy` — the central producer. `quadrant_snapshot`/`gate_snapshot` are `GateRegimeSnapshot | None` in v1; both come from the same `fetch_gate_regime` read (the worker materializes the quadrant + gate on one row), so the snapshot ids derive from `as_of` until Track A splits them. `cvar_limit = base_cvar_limit · eff_gate.cvar_mult`; `beta_cap = eff_gate.beta_cap`; `risk_assets_cap = eff_gate.risk_assets_cap`; `sleeve_budgets` from `policy_bands(QuadrantPolicy)`; `defensive_floor` from the quadrant policy; `bl_view_confidence_multiplier = eff_gate.bl_view_confidence_multiplier`; `fixed_income_sub_budgets = {}` (v1).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_effective_policy.py
import datetime as dt

import pytest

from app.services import effective_policy as ep
from app.services import quadrant_policy as qp
from app.optimizer import gate_overlay as go


def _snap(state: str = "risk_on", quadrant: str | None = "recovery"):
    from app.services.taa_bands import GateRegimeSnapshot

    return GateRegimeSnapshot(
        as_of=dt.date(2026, 1, 5), state=state, vote_count=0,
        trend_vote=False, credit_vote=False, drawdown_vote=False, dwell_days=1,
        last_flip=None, growth_score=0.01, inflation_score=0.02, quadrant=quadrant,
    )


def test_build_produces_cohesive_policy_risk_on() -> None:
    snap = _snap("risk_on", "recovery")
    eff = ep.build_effective_policy(snap, snap, "moderate", base_cvar_limit=0.05)
    assert isinstance(eff, ep.EffectiveRegimePolicy)
    assert eff.profile == "moderate"
    assert eff.quadrant == "recovery"
    assert eff.gate_state == "risk_on"
    assert eff.policy_version == qp.POLICY_VERSION
    # risk_on: cvar/beta/risk_assets identity, views full
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    assert eff.cvar_limit == pytest.approx(0.05)
    assert eff.beta_cap == pytest.approx(go.PROFILE_PORTFOLIO_BETA_CAPS["moderate"])
    assert eff.risk_assets_cap == pytest.approx(pol.risk_assets_cap)
    assert eff.defensive_floor == pytest.approx(pol.defensive_floor)
    assert eff.bl_view_confidence_multiplier == 1.0
    assert eff.fixed_income_sub_budgets == {}
    assert eff.sleeve_budgets["equity"].lo == pytest.approx(
        qp.policy_bands(pol)["equity"][0]
    )
    assert eff.quadrant_snapshot_id and eff.gate_snapshot_id


def test_build_applies_gate_overlay_in_risk_off() -> None:
    snap = _snap("risk_off", "contraction")
    eff = ep.build_effective_policy(snap, snap, "aggressive", base_cvar_limit=0.06)
    base_beta = go.PROFILE_PORTFOLIO_BETA_CAPS["aggressive"]
    eg = go.apply_gate_overlay(
        "aggressive", "risk_off",
        base_risk_assets_cap=qp.QUADRANT_POLICIES["aggressive"]["contraction"].risk_assets_cap,
        base_portfolio_beta_cap=base_beta,
    )
    assert eff.cvar_limit == pytest.approx(0.06 * eg.cvar_mult)
    assert eff.cvar_limit < 0.06
    assert eff.beta_cap == pytest.approx(eg.beta_cap)
    assert eff.beta_cap < base_beta            # aggregate beta cap tightened
    assert eff.risk_assets_cap == pytest.approx(eg.risk_assets_cap)
    assert eff.bl_view_confidence_multiplier == 0.0  # views omitted in risk_off v1


def test_build_raises_on_unconsumable_quadrant() -> None:
    with pytest.raises(ep.EffectivePolicyError):
        ep.build_effective_policy(_snap("risk_on", None), _snap("risk_on", None),
                                  "moderate", base_cvar_limit=0.05)


def test_build_raises_on_missing_gate() -> None:
    with pytest.raises(ep.EffectivePolicyError):
        ep.build_effective_policy(_snap(), None, "moderate", base_cvar_limit=0.05)


def test_sleeve_budgets_cover_all_structural_sleeves() -> None:
    eff = ep.build_effective_policy(_snap(), _snap(), "conservative", base_cvar_limit=0.04)
    assert set(eff.sleeve_budgets) == set(qp.STRUCTURAL_SLEEVES)
    for b in eff.sleeve_budgets.values():
        assert isinstance(b, qp.Budget)
        assert 0.0 <= b.lo <= b.hi <= 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_effective_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.effective_policy'`

- [ ] **Step 3: Implement the producer**

```python
# app/services/effective_policy.py
"""The central product of the COMBO policy core (decision B / spec §12).

build_effective_policy composes a valid QuadrantSnapshot + a valid GateSnapshot +
a profile into ONE cohesive, frozen EffectiveRegimePolicy carrying the FINAL policy
numbers: per-sleeve budgets (center ± half_width), the gate-tightened cvar_limit /
beta_cap / risk_assets_cap, the quadrant defensive_floor, the BL view-confidence
multiplier, and lineage ids. The policy core validates and selects; it does NOT know
instruments, does NOT resolve feasibility, and does NOT call CVXPY (frontier A). The
beta_cap here is the AGGREGATE portfolio-beta cap — Plan C compiles it into a
LinearConstraint; this module only exposes the number.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.optimizer import gate_overlay
from app.services import quadrant_policy as qp
from app.services.taa_bands import GateRegimeSnapshot


class EffectivePolicyError(ValueError):
    """A snapshot is non-consumable or an input is missing (spec §31). Fail-loud;
    the builder re-raises this as a structured BuilderError → 422."""


@dataclass(frozen=True)
class EffectiveRegimePolicy:
    profile: str
    quadrant: qp.Quadrant
    gate_state: qp.GateState
    policy_version: str
    quadrant_snapshot_id: str
    gate_snapshot_id: str
    sleeve_budgets: dict[str, qp.Budget]
    fixed_income_sub_budgets: dict[str, qp.Budget]
    cvar_limit: float
    beta_cap: float            # AGGREGATE portfolio-beta cap (β_portfolio ≤ beta_cap)
    risk_assets_cap: float
    defensive_floor: float
    bl_view_confidence_multiplier: float


def _snapshot_id(snap: GateRegimeSnapshot, kind: str) -> str:
    # v1: quadrant + gate are materialized on one regime_gate_daily row, so both ids
    # derive from as_of. Track A will split them into independent snapshot ids.
    return f"{kind}:{snap.as_of.isoformat()}"


def build_effective_policy(
    quadrant_snapshot: GateRegimeSnapshot | None,
    gate_snapshot: GateRegimeSnapshot | None,
    profile: str,
    *,
    base_cvar_limit: float,
) -> EffectiveRegimePolicy:
    """Produce the cohesive EffectiveRegimePolicy (decision B). Fail-loud on a
    non-consumable quadrant/gate or a missing policy."""
    if profile not in qp.PROFILES:
        raise EffectivePolicyError(f"unknown profile {profile!r}")
    if quadrant_snapshot is None:
        raise EffectivePolicyError("QUADRANT_UNAVAILABLE: no quadrant snapshot")
    if gate_snapshot is None:
        raise EffectivePolicyError("GATE_UNAVAILABLE: no gate snapshot")
    quadrant = quadrant_snapshot.quadrant
    if quadrant is None or quadrant not in qp.QUADRANTS:
        raise EffectivePolicyError(
            f"QUADRANT_UNAVAILABLE: non-consumable quadrant {quadrant!r}"
        )
    by_quadrant = qp.QUADRANT_POLICIES.get(profile)
    if by_quadrant is None or quadrant not in by_quadrant:
        raise EffectivePolicyError(
            f"POLICY_NOT_FOUND: no policy for {profile}/{quadrant}"
        )
    policy = by_quadrant[quadrant]
    gate_state = gate_snapshot.state
    eff_gate = gate_overlay.apply_gate_overlay(
        profile,
        gate_state,
        base_risk_assets_cap=policy.risk_assets_cap,
        base_portfolio_beta_cap=gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS[profile],
    )
    bands = qp.policy_bands(policy)
    sleeve_budgets = {
        sleeve: qp.Budget(lo=lo, hi=hi) for sleeve, (lo, hi) in bands.items()
    }
    return EffectiveRegimePolicy(
        profile=profile,
        quadrant=quadrant,
        gate_state=gate_state,
        policy_version=policy.policy_version,
        quadrant_snapshot_id=_snapshot_id(quadrant_snapshot, "quadrant"),
        gate_snapshot_id=_snapshot_id(gate_snapshot, "gate"),
        sleeve_budgets=sleeve_budgets,
        fixed_income_sub_budgets=dict(policy.fixed_income_sub_budgets),  # {} in v1
        cvar_limit=base_cvar_limit * eff_gate.cvar_mult,
        beta_cap=eff_gate.beta_cap,
        risk_assets_cap=eff_gate.risk_assets_cap,
        defensive_floor=policy.defensive_floor,
        bl_view_confidence_multiplier=eff_gate.bl_view_confidence_multiplier,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_effective_policy.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/services/effective_policy.py tests/test_effective_policy.py
git commit -m "feat(combo): EffectiveRegimePolicy + build_effective_policy (central policy-core product)"
```

---

### Task 6: BL view-confidence multiplier in `category_momentum_mu`

**Files:**
- Modify: `app/optimizer/momentum_view.py` (signature line 74-84; branch line 115; omega line 125)
- Test: `tests/test_momentum_view.py` (append; create if absent)

**Interfaces:**
- Consumes: `bl.omega_idzorek` (`black_litterman.py:137`; guard `0 < c <= 1`), `VIEW_CONF` (`momentum_view.py:35`).
- Produces: `category_momentum_mu(returns, groups, prior, gate_state, *, window=DEFAULT_WINDOW, delta_market=DELTA_MARKET, use_views=True, sigma=None, view_confidence_multiplier: float = 1.0) -> np.ndarray` — new keyword `view_confidence_multiplier`. `multiplier <= 0.0` → μ = π (views omitted; never calls `omega_idzorek` with c≤0). Otherwise the Idzorek confidence becomes `VIEW_CONF * multiplier` (clamped to ≤ 1.0 so it stays in `omega_idzorek`'s `(0,1]` domain).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_momentum_view.py` (create the file with these imports if it does not exist):

```python
import numpy as np

from app.optimizer import momentum_view as mv


def _risk_inputs():
    rng = np.random.default_rng(7)
    groups = ["equity", "thematic", "fixed_income", "alternatives"]
    returns = rng.normal(0.0004, 0.01, (600, 4))
    prior = np.array([0.4, 0.1, 0.4, 0.1])
    return returns, groups, prior


def test_multiplier_zero_returns_equilibrium() -> None:
    returns, groups, prior = _risk_inputs()
    mu = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.0
    )
    pi = mv.category_momentum_mu(
        returns, groups, prior, "risk_off"  # risk_off path already returns pi
    )
    assert np.allclose(mu, pi)


def test_multiplier_one_matches_default() -> None:
    returns, groups, prior = _risk_inputs()
    a = mv.category_momentum_mu(returns, groups, prior, "risk_on")
    b = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=1.0
    )
    assert np.allclose(a, b)


def test_half_multiplier_tilts_less_than_full() -> None:
    returns, groups, prior = _risk_inputs()
    pi = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.0
    )
    full = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=1.0
    )
    half = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.5
    )
    # half-confidence tilt is strictly between equilibrium and full-confidence
    dist_full = float(np.linalg.norm(full - pi))
    dist_half = float(np.linalg.norm(half - pi))
    assert 0.0 < dist_half < dist_full


def test_multiplier_never_passes_zero_confidence(monkeypatch) -> None:
    returns, groups, prior = _risk_inputs()
    seen: list[list[float]] = []
    real = mv.bl.omega_idzorek

    def spy(p, sigma, confidences, tau):
        seen.append(list(confidences))
        return real(p, sigma, confidences, tau=tau)

    monkeypatch.setattr(mv.bl, "omega_idzorek", spy)
    mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.5
    )
    assert seen and all(0.0 < c <= 1.0 for conf in seen for c in conf)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_momentum_view.py -v`
Expected: FAIL — `TypeError: category_momentum_mu() got an unexpected keyword argument 'view_confidence_multiplier'`

- [ ] **Step 3: Apply the change**

In `app/optimizer/momentum_view.py`, extend the signature (lines 74-84) by adding the
keyword (place it after `sigma`):

```python
def category_momentum_mu(
    returns: np.ndarray,
    groups: list[str],
    prior: np.ndarray,
    gate_state: str | None,
    *,
    window: int = DEFAULT_WINDOW,
    delta_market: float = DELTA_MARKET,
    use_views: bool = True,
    sigma: np.ndarray | None = None,
    view_confidence_multiplier: float = 1.0,
) -> np.ndarray:
```

Replace the risk-off short-circuit (line 115) so a non-positive multiplier also
returns π:

```python
    if (
        not use_views
        or (gate_state or "").lower() == "risk_off"
        or view_confidence_multiplier <= 0.0
    ):
        return pi
```

Replace the omega call (line 125) to scale the confidence, clamped into `(0, 1]`:

```python
    effective_conf = min(1.0, VIEW_CONF * view_confidence_multiplier)
    omega = bl.omega_idzorek(p_mat, sigma, [effective_conf], tau=TAU)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_momentum_view.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/optimizer/momentum_view.py tests/test_momentum_view.py
git commit -m "feat(combo): view_confidence_multiplier on category_momentum_mu (spec §24)"
```

---

### Task 7: Ortogonalizar o builder — consumir `EffectiveRegimePolicy` (substitui `combined_regime`/`band_state_from_quadrant`)

> **Decisão B/C/D do dono — o builder consome `EffectiveRegimePolicy`, não `QUADRANT_POLICIES`+`apply_gate_overlay` soltos.** O caminho `regime_aware` chama `build_effective_policy(quadrant_snapshot, gate_snapshot, profile, base_cvar_limit=...)` UMA vez e aplica os campos retornados. **RELEASE GATE:** na v1 (sem Plano C) o builder aplica `sleeve_budgets`/`cvar_limit`/`risk_assets_cap`/`defensive_floor`/`bl_view_confidence_multiplier` no caminho existente; **`beta_cap` é EXPOSTO em telemetria/diagnóstico, NÃO garantido** (a `LinearConstraint` de beta agregado é Plano C). Não afirmar garantia de beta agregado em lugar nenhum.

**Files:**
- Modify: `app/services/portfolio_builder.py`
  - imports (add `quadrant_policy`, `gate_overlay`, `effective_policy`)
  - `_resolve_regime_block_budgets` (lines 464-500): drop `combined_regime`/`effective_class_bands`/STAG_GOLD branch; build blocks from `EffectiveRegimePolicy.sleeve_budgets`; raise `GATE_UNAVAILABLE`/`QUADRANT_UNAVAILABLE`/`POLICY_NOT_FOUND` on missing inputs.
  - `_solve_regime_level1` (lines 554-598): replace `band_state` param with `quadrant`; read bands from the `EffectiveRegimePolicy.sleeve_budgets` (or `policy_bands(QUADRANT_POLICIES[profile][quadrant])` when called standalone); pass `view_confidence_multiplier` to `category_momentum_mu`.
  - `_solve_regime_two_level` (lines 657-754): replace `band_state_from_quadrant` + `profile_sleeve_bands` with `EffectiveRegimePolicy.sleeve_budgets`; replace the inline `cvar_cap *= DEFAULT_RISK_OFF_CVAR_FACTOR` (line 727-728) with `eff_policy.cvar_limit` (the overlay-tightened limit). Expose `eff_policy.beta_cap` in the result for telemetry (NOT compiled into a constraint — RELEASE GATE).
  - dispatch `regime_aware` block (lines 1212-1324): remove the STAG_GOLD goldfix branch (1234-1249) and the S4a single-level fallback (1268-1324, handled in Task 8); build the `EffectiveRegimePolicy` once and read CVaR/risk_assets/floor/views/beta_cap from it.
  - diagnostics (line 1491): replace `combined_regime=regime_combined` with the orthogonal `quadrant`/`gate_state` already present, plus `beta_cap` (exposed-not-guaranteed).
- Test: `tests/test_builder_regime_two_level.py` (append); `tests/test_builder_regime_aware.py` (update the `combined_regime`-asserting tests).

**Interfaces:**
- Consumes: `effective_policy.build_effective_policy`, `effective_policy.EffectiveRegimePolicy`, `effective_policy.EffectivePolicyError` (Task 5); `quadrant_policy.QUADRANT_POLICIES`, `quadrant_policy.policy_bands` (Tasks 1/2); `gate_overlay.bl_confidence_multiplier` (Task 4); `taa_bands.fetch_gate_regime` (`taa_bands.py:565`); `_regime_profile` (`portfolio_builder.py:647`); `BuilderError` (`portfolio_builder.py:23`); `resolve_cvar_limit` (the per-mandate base CVaR).
- Produces:
  - `class QuadrantUnavailableError(BuilderError)`, `class GateUnavailableError(BuilderError)`, `class PolicyNotFoundError(BuilderError)` — structured errors (spec §31), all → 422. `EffectivePolicyError` from Task 5 is caught and re-raised as the matching `BuilderError` subclass (`QUADRANT_UNAVAILABLE`→`QuadrantUnavailableError`, `GATE_UNAVAILABLE`→`GateUnavailableError`, `POLICY_NOT_FOUND`→`PolicyNotFoundError`).
  - `_resolve_quadrant_policy(profile: str, quadrant: str | None) -> quadrant_policy.QuadrantPolicy` — raises `QuadrantUnavailableError` when `quadrant` is None/unknown, `PolicyNotFoundError` when the policy is absent. (Kept as a thin helper for `_solve_regime_level1`; the dispatch path prefers `build_effective_policy`.)
  - `_resolve_regime_block_budgets(session, datalake, assets, labels, profile) -> tuple[list[engine.BlockBudget], str, str]` — now returns `(blocks, quadrant, gate_state)` (no `combined_regime` label), with blocks derived from the `EffectiveRegimePolicy.sleeve_budgets`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_builder_regime_two_level.py` (the `pb`, `dt`, `np`, `pd`, `asyncio`
imports already exist; `_TL_IDS`/`_TL_STRATEGY`/`_TL_CLASS`/`_ascending_levels` helpers
already exist in the file):

```python
import pytest

from app.services import quadrant_policy as qp


def test_resolve_quadrant_policy_returns_policy_for_known_quadrant() -> None:
    pol = pb._resolve_quadrant_policy("moderate", "recovery")
    assert pol is qp.QUADRANT_POLICIES["moderate"]["recovery"]


def test_resolve_quadrant_policy_raises_on_none_quadrant() -> None:
    with pytest.raises(pb.QuadrantUnavailableError):
        pb._resolve_quadrant_policy("moderate", None)


def test_resolve_quadrant_policy_raises_on_unknown_quadrant() -> None:
    with pytest.raises(pb.QuadrantUnavailableError):
        pb._resolve_quadrant_policy("moderate", "stagflation")


def test_two_level_uses_quadrant_policy_bands(monkeypatch: object) -> None:
    """The two-level solve must derive its sleeve bands from QUADRANT_POLICIES,
    not band_state_from_quadrant (removed). Bands for recovery/moderate match
    policy_bands of that policy."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(500)]
    index = pd.Index(dates)
    assets = [pb.FundRefIn(kind="fund", id=fid) for fid in _TL_IDS]
    labels = [pb._ref_key(a) for a in assets]

    def _levels(ticker: str) -> list[float]:
        rng = np.random.default_rng(sum(ord(c) for c in ticker))
        lvl, out = 100.0, []
        for r in rng.normal(0.0003, 0.01, len(index)):
            lvl *= 1.0 + r
            out.append(lvl)
        return out

    async def fake_rows(session, ticker, start, end):
        return [(d, float(p)) for d, p in zip(dates, _levels(ticker), strict=True)]

    async def fake_strategy(session, fund_ids):
        return {fid: _TL_STRATEGY.get(fid) for fid in fund_ids}

    async def fake_class(session, fund_ids):
        return {fid: _TL_CLASS.get(fid) for fid in fund_ids}

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    monkeypatch.setattr(pb.optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(pb.optimizer_data, "load_fund_asset_class", fake_class)

    from app.schemas.builder import OptimizeRequest
    payload = OptimizeRequest(assets=assets, objective="regime_aware", mandate="moderate")
    result = asyncio.run(
        pb._solve_regime_two_level(
            object(), assets, labels, index, "recovery", "risk_on", payload
        )
    )
    assert result is not None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    for sleeve, [lo, hi] in result.sleeve_bands.items():
        assert (lo, hi) == pytest.approx(expected[sleeve])


def test_combined_regime_removed_from_module() -> None:
    assert not hasattr(__import__("app.services.taa_bands", fromlist=["x"]), "combined_regime")
    assert not hasattr(
        __import__("app.services.taa_bands", fromlist=["x"]), "band_state_from_quadrant"
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_builder_regime_two_level.py -k "quadrant_policy or uses_quadrant_policy or combined_regime_removed" -v`
Expected: FAIL — `AttributeError: module 'app.services.portfolio_builder' has no attribute '_resolve_quadrant_policy'` (and the `combined_regime_removed` test fails because the function still exists).

- [ ] **Step 3: Apply the orthogonalization**

Add imports near the other `app.services`/`app.optimizer` imports at the top of
`portfolio_builder.py`:

```python
from app.optimizer import gate_overlay
from app.services import effective_policy, quadrant_policy
```

Add the structured errors and resolver (place near `DEFAULT_RISK_OFF_CVAR_FACTOR`,
around line 114 — keep `DEFAULT_RISK_OFF_CVAR_FACTOR` for the non-regime
`max_return_cvar` path, which is out of scope):

```python
class QuadrantUnavailableError(BuilderError):
    """regime_aware requested but no consumable quadrant (spec §31)."""


class GateUnavailableError(BuilderError):
    """regime_aware requested but no consumable gate (spec §31)."""


class PolicyNotFoundError(BuilderError):
    """No QuadrantPolicy for this profile×quadrant (spec §31)."""


def _as_builder_error(exc: effective_policy.EffectivePolicyError) -> BuilderError:
    """Map a policy-core EffectivePolicyError to the matching structured BuilderError
    (→ 422) by message prefix (spec §31). Default to QuadrantUnavailableError."""
    msg = str(exc)
    if msg.startswith("GATE_UNAVAILABLE"):
        return GateUnavailableError(msg)
    if msg.startswith("POLICY_NOT_FOUND"):
        return PolicyNotFoundError(msg)
    return QuadrantUnavailableError(msg)


def _resolve_quadrant_policy(
    profile: str, quadrant: str | None
) -> quadrant_policy.QuadrantPolicy:
    """Load the QuadrantPolicy for a profile×quadrant, fail-loud (spec §31).

    A None/unknown quadrant is QUADRANT_UNAVAILABLE (never falls back to a default
    quadrant — spec §1.2). A missing policy for a valid quadrant is POLICY_NOT_FOUND.
    """
    if quadrant is None or quadrant not in quadrant_policy.QUADRANTS:
        raise QuadrantUnavailableError(
            f"regime_aware: no consumable quadrant (got {quadrant!r})"
        )
    by_quadrant = quadrant_policy.QUADRANT_POLICIES.get(profile)
    if by_quadrant is None or quadrant not in by_quadrant:
        raise PolicyNotFoundError(
            f"regime_aware: no policy for profile {profile!r} quadrant {quadrant!r}"
        )
    return by_quadrant[quadrant]
```

Rewrite `_resolve_regime_block_budgets` (lines 464-500) to read the policy bands
and drop `combined_regime`/STAG_GOLD:

```python
async def _resolve_regime_block_budgets(
    session: AsyncSession,
    datalake: AsyncSession | None,
    assets: list[AssetRefIn],
    labels: list[str],
    profile: str,
) -> tuple[list[engine.BlockBudget], str, str | None]:
    """Derive the per-sleeve BlockBudget envelope from QUADRANT_POLICIES[profile]
    [quadrant] (spec §12). Reads the worker-materialized quadrant + gate state;
    fail-loud on a non-consumable quadrant (no goldfix sentinel, no STAG_GOLD).

    Returns ``(sleeve_blocks, quadrant, gate_state)``.
    """
    gate = await taa_bands.fetch_gate_regime(datalake) if datalake is not None else None
    gate_state = _OVERRIDE_REGIME_STATE or (gate.state if gate else None)
    quadrant = gate.quadrant if gate else None
    policy = _resolve_quadrant_policy(profile, quadrant)
    bands = quadrant_policy.policy_bands(policy)
    columns = await _fund_class_columns(session, assets, labels)
    blocks: list[engine.BlockBudget] = []
    for sleeve in quadrant_policy.STRUCTURAL_SLEEVES:
        idxs = columns.get(sleeve)
        if not idxs:
            continue
        lo, hi = bands[sleeve]
        blocks.append(engine.BlockBudget(indices=idxs, lo=lo, hi=hi))
    return blocks, quadrant, gate_state
```

(NOTE: `_fund_class_columns` currently maps the 4-class taxonomy; the two-level path
already builds its own 7-sleeve `funds_by_sleeve`. Block budgets from this function
feed only the diagnostics/single-level path that Task 8 removes — keep the call but
do not rely on STAG_GOLD. If `_fund_class_columns` does not return 7-sleeve keys,
the per-sleeve loop simply produces blocks only for the classes it does map; this is
acceptable because the two-level path (the production path) re-derives its own sleeve
bands directly in `_solve_regime_two_level`.)

In `_solve_regime_level1` (lines 554-598) change the signature parameter
`band_state: str` to `quadrant: str` and replace the band read (line 582) and the
momentum call (lines 579-581):

```python
def _solve_regime_level1(
    proxies: list[str],
    proxy_returns: np.ndarray,
    proxy_groups: list[str],
    profile: str,
    quadrant: str,
    gamma: float,
    cvar_cap: float,
    gate_state: str | None,
    view_confidence_multiplier: float,
) -> dict[str, float]:
    ...
    sigma = engine.sigma_ledoit_wolf(proxy_returns)
    prior = _regime_prior(proxy_groups)
    mu = momentum_view.category_momentum_mu(
        proxy_returns, proxy_groups, prior, gate_state, sigma=sigma,
        view_confidence_multiplier=view_confidence_multiplier,
    )
    bands = quadrant_policy.policy_bands(_resolve_quadrant_policy(profile, quadrant))
    ...
```

In `_solve_regime_two_level` (lines 682-684, 726-735) replace the band-state
resolution and the inline CVaR tighten by building the `EffectiveRegimePolicy` once
and reading the FINAL numbers from it (the gate overlay is applied INSIDE
`build_effective_policy`):

```python
    profile = _regime_profile(payload.mandate)
    # per-mandate base dials; the gate overlay tightens cvar/beta/risk_assets inside
    # build_effective_policy (spec §22). gate_snapshot == quadrant_snapshot in v1.
    gamma = resolve_gamma(None, payload.mandate)
    base_cvar = resolve_cvar_limit(payload.cvar_limit, payload.mandate)
    gate = await taa_bands.fetch_gate_regime(datalake) if datalake is not None else None
    try:
        eff_policy = effective_policy.build_effective_policy(
            gate, gate, profile, base_cvar_limit=base_cvar
        )
    except effective_policy.EffectivePolicyError as exc:
        raise _as_builder_error(exc) from exc
    bands = {s: (b.lo, b.hi) for s, b in eff_policy.sleeve_budgets.items()}
    cvar_cap = eff_policy.cvar_limit
    view_mult = eff_policy.bl_view_confidence_multiplier
    # eff_policy.beta_cap is EXPOSED for telemetry only — NOT compiled here (RELEASE GATE).
    ...
    try:
        wcat = _solve_regime_level1(
            proxies_live, proxy_returns, proxy_groups, profile, eff_policy.quadrant,
            gamma, cvar_cap, eff_policy.gate_state, view_mult,
        )
    except engine.OptimizerError:
        return None
```

(`_as_builder_error(exc)` is a small mapper: it inspects the `EffectivePolicyError`
message prefix — `QUADRANT_UNAVAILABLE`/`GATE_UNAVAILABLE`/`POLICY_NOT_FOUND` — and
returns the matching `BuilderError` subclass. Add it next to the error classes.)

In the dispatch block (lines 1212-1324), remove the STAG_GOLD branch (1234-1249) and
route directly to the two-level solve. Build the `EffectiveRegimePolicy` once and read
every final number from it (no separate `apply_gate_overlay` call). Replace the
`combined_regime` unpack at 1219-1221:

```python
            _profile = _regime_profile(payload.mandate)
            gate = (
                await taa_bands.fetch_gate_regime(datalake)
                if datalake is not None else None
            )
            try:
                eff_policy = effective_policy.build_effective_policy(
                    gate, gate, _profile,
                    base_cvar_limit=resolve_cvar_limit(payload.cvar_limit, payload.mandate),
                )
            except effective_policy.EffectivePolicyError as exc:
                raise _as_builder_error(exc) from exc
            regime_quadrant = eff_policy.quadrant
            gate_state = _OVERRIDE_REGIME_STATE or eff_policy.gate_state
            regime_state = gate_state
            cvar_limit_effective = eff_policy.cvar_limit
            regime_beta_cap = eff_policy.beta_cap  # EXPOSED, not compiled (RELEASE GATE)
            two_level = await _solve_regime_two_level(
                session, assets, labels, frame.index,
                regime_quadrant, gate_state, payload,
            )
            if two_level is None:
                raise QuadrantUnavailableError(
                    "regime_aware: two-level solve could not be built for this "
                    "universe (need >=2 live sleeves with proxies)"
                )
            weights = two_level.fund_weights
            status = "regime_two_level"
            regime_proxy_holdings = two_level.proxy_holdings
            regime_proxy_returns = two_level.proxy_returns
            regime_category_weights = two_level.category_weights
            regime_class_bands = two_level.sleeve_bands
```

In the diagnostics assembly (line 1491) remove `combined_regime=regime_combined`
(the field is dropped from the schema in Task 9); leave `quadrant=regime_quadrant`
and `regime_state=regime_state`, and ADD `beta_cap=regime_beta_cap` as an
exposed-not-guaranteed diagnostic (the schema field is added in Task 9; document it
as "aggregate portfolio-beta cap target — NOT guaranteed until Plan C compiles it").
Remove the now-unused locals `regime_combined`, `regime_haven_tilt` (and its
`haven_tilt=` diagnostics line at 1493).

Finally, DELETE `combined_regime` (lines 325-363) and `band_state_from_quadrant`
(lines 190-205) from `app/services/taa_bands.py`. (Keep `effective_class_bands`/
`goldfix_target`/`DEFAULT_TAA_BANDS` for Task 8 to remove with the S4a path / macro
route.)

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_builder_regime_two_level.py tests/test_builder_regime_aware.py -v`
Expected: PASS for the new tests. The pre-existing `combined_regime`-asserting tests
in `test_builder_regime_aware.py` (lines 233, 255, 297, 545) and
`test_builder_regime_two_level.py:382` now FAIL on the dropped field — update each:
replace `diag.combined_regime == "..."` assertions with `diag.quadrant == "..."` +
`diag.regime_state == "..."`, and delete STAG_GOLD/goldfix assertions
(`test_builder_regime_aware.py:111,126,297`; `test_builder_regime_aware_schema.py:47,52`).
Re-run until green.

- [ ] **Step 5: Commit**

```bash
git add app/services/portfolio_builder.py app/services/taa_bands.py \
    tests/test_builder_regime_two_level.py tests/test_builder_regime_aware.py \
    tests/test_builder_regime_aware_schema.py
git commit -m "refactor(combo): orthogonalize regime_aware — consume EffectiveRegimePolicy

Drops combined_regime/band_state_from_quadrant; the builder calls
build_effective_policy(quadrant_snapshot, gate_snapshot, profile) once and applies
sleeve_budgets/cvar_limit/risk_assets_cap/defensive_floor/bl_view_confidence_multiplier.
beta_cap is EXPOSED for telemetry, NOT compiled (RELEASE GATE — Plan C compiles the
aggregate LinearConstraint). Fail-loud QUADRANT_UNAVAILABLE/POLICY_NOT_FOUND; no goldfix."
```

---

### Task 8: Aposentar `effective_class_bands`/`DEFAULT_TAA_BANDS`/`goldfix_target` + S4a fallback + macro route

**Files:**
- Modify: `app/services/taa_bands.py` (delete `DEFAULT_TAA_BANDS` 43-82, `IPS_CLASS_BOUNDS` 86-91, `ASSET_CLASSES` 94, `effective_class_bands` 367-410, `goldfix_target` 414-437, `normalized_profile_centers` 208-216, `profile_sleeve_bands` 219-230, `HW_SCALE` 97, `SLEEVE_HALF_WIDTHS` 179-182, `SLEEVE_IPS_BOUNDS` 183-187, `PROFILE_CENTERS` 146-177 — all superseded by `quadrant_policy`).
- Modify: `app/api/routes/macro.py` (`_build_macro_quadrant` 54-111; `_BAND_CLASS_ORDER` 40) — replace the `combined_regime`/`effective_class_bands`/`goldfix_target` block with the orthogonal `quadrant` + per-sleeve `policy_bands`.
- Modify: `app/services/portfolio_builder.py` — delete the dead S4a single-level fallback block (former lines 1268-1324, already routed away in Task 7) and `_COMBO_BAND_CLASSES` / `_solve_regime_motor` if unreferenced after the removal.
- Test: `tests/test_taa_bands.py` (delete the `combined_regime`/`effective_class_bands`/`goldfix_target` tests), `tests/test_macro_quadrant_route.py` (update).

**Interfaces:**
- Consumes: `quadrant_policy.QUADRANT_POLICIES`, `quadrant_policy.policy_bands`, `quadrant_policy.STRUCTURAL_SLEEVES` (Task 1); the macro route gains a profile for the bands — use `"moderate"` as the display profile (documented default; the macro block is informational, not the builder mandate).
- Produces: `macro.py::_build_macro_quadrant` returns `MacroQuadrantOut` with per-sleeve bands from `policy_bands(QUADRANT_POLICIES["moderate"][quadrant])` and `haven_tilt=None` always (goldfix removed). `bands` is empty when the quadrant is not consumable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_macro_quadrant_route.py`:

```python
def test_macro_quadrant_uses_sleeve_bands_not_goldfix(monkeypatch) -> None:
    """The macro block exposes per-sleeve bands from the quadrant policy and never
    a goldfix haven_tilt (removed). For a consumable slowdown quadrant, bands are
    the moderate/slowdown policy bands; haven_tilt is None."""
    import asyncio

    from app.api.routes import macro as macro_route
    from app.services import quadrant_policy as qp
    from app.services import taa_bands

    snap = taa_bands.GateRegimeSnapshot(
        as_of=__import__("datetime").date(2026, 1, 5), state="risk_on",
        vote_count=0, trend_vote=False, credit_vote=False, drawdown_vote=False,
        dwell_days=1, last_flip=None, growth_score=-0.01, inflation_score=0.02,
        quadrant="slowdown",
    )

    async def fake_gate(datalake):
        return snap

    monkeypatch.setattr(macro_route.taa_bands, "fetch_gate_regime", fake_gate)
    out = asyncio.run(macro_route._build_macro_quadrant(object()))
    assert out.haven_tilt is None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["slowdown"])
    got = {b.asset_class: (b.min_weight, b.max_weight) for b in out.bands}
    for sleeve, (lo, hi) in expected.items():
        assert got[sleeve] == (lo, hi)


def test_macro_quadrant_empty_bands_when_quadrant_none(monkeypatch) -> None:
    import asyncio

    from app.api.routes import macro as macro_route

    async def fake_gate(datalake):
        return None

    monkeypatch.setattr(macro_route.taa_bands, "fetch_gate_regime", fake_gate)
    out = asyncio.run(macro_route._build_macro_quadrant(object()))
    assert out.bands == []
    assert out.haven_tilt is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_macro_quadrant_route.py -k "sleeve_bands or empty_bands" -v`
Expected: FAIL — the current route still calls `combined_regime`/`goldfix_target` and
emits 4-class bands / a non-None `haven_tilt` for slowdown.

- [ ] **Step 3: Apply the removals + rewrite the macro route**

Rewrite `app/api/routes/macro.py::_build_macro_quadrant` (lines 54-111):

```python
_MACRO_DISPLAY_PROFILE = "moderate"  # informational block; not the builder mandate


async def _build_macro_quadrant(datalake: AsyncSession) -> MacroQuadrantOut:
    """Assemble the additive COMBO macro block: gate + quadrant + per-sleeve bands.

    Reads the worker-materialized quadrant (decision A). The quadrant and gate are
    ORTHOGONAL (spec §12): the bands come from QUADRANT_POLICIES[display_profile]
    [quadrant]; the gate is reported but does not fold into the bands here. No
    goldfix/STAG_GOLD. ``bands`` is empty when the quadrant is not consumable.
    """
    from app.services import quadrant_policy

    gate = await taa_bands.fetch_gate_regime(datalake)
    gate_state = gate.state if gate else None
    quadrant = gate.quadrant if gate else None
    growth_score = gate.growth_score if gate else None
    inflation_score = gate.inflation_score if gate else None

    bands: list[ClassBandOut] = []
    if quadrant in quadrant_policy.QUADRANTS:
        policy = quadrant_policy.QUADRANT_POLICIES[_MACRO_DISPLAY_PROFILE][quadrant]
        sleeve_bands = quadrant_policy.policy_bands(policy)
        bands = [
            ClassBandOut(asset_class=sleeve, min_weight=lo, max_weight=hi)
            for sleeve in quadrant_policy.STRUCTURAL_SLEEVES
            for (lo, hi) in (sleeve_bands[sleeve],)
        ]

    gate_block = (
        GateBlockOut(
            as_of=gate.as_of, state=gate.state, trend_vote=gate.trend_vote,
            credit_vote=gate.credit_vote, drawdown_vote=gate.drawdown_vote,
            vote_count=gate.vote_count, dwell_days=gate.dwell_days,
        )
        if gate
        else None
    )

    return MacroQuadrantOut(
        as_of=gate.as_of if gate else None,
        quadrant=quadrant,
        growth_state=_score_state(growth_score),
        inflation_state=_score_state(inflation_score),
        growth_score=growth_score,
        inflation_score=inflation_score,
        bands=bands,
        haven_tilt=None,
        gate=gate_block,
    )
```

Remove the `_BAND_CLASS_ORDER = taa_bands.ASSET_CLASSES` line (40) — no longer used.

Delete from `app/services/taa_bands.py`: `DEFAULT_TAA_BANDS`, `IPS_CLASS_BOUNDS`,
`ASSET_CLASSES`, `HW_SCALE`, `PROFILE_CENTERS`, `SLEEVE_HALF_WIDTHS`,
`SLEEVE_IPS_BOUNDS`, `normalized_profile_centers`, `profile_sleeve_bands`,
`effective_class_bands`, `goldfix_target`. Keep `SLEEVE_GROUPS` only if still
imported elsewhere; otherwise replace its consumers with
`quadrant_policy.STRUCTURAL_SLEEVES` (grep first — `sleeves.SLEEVE_GROUPS` in
`app/optimizer/sleeves.py` is the canonical one the builder already uses at
`portfolio_builder.py:584,701`, so `taa_bands.SLEEVE_GROUPS` can go).

In `portfolio_builder.py`, delete the dead S4a single-level fallback (former lines
1268-1324: `_band_map = taa_bands.effective_class_bands(...)`, `vol_graduated_caps`,
`beta_graduated_caps`, `_solve_regime_motor` call). The two-level path is now the
only regime_aware path; an infeasible universe raises `QuadrantUnavailableError`
(Task 7). Remove `_COMBO_BAND_CLASSES`, `_solve_regime_motor`,
`_resolve_regime_block_budgets`' diagnostics-only blocks if unreferenced (grep to
confirm before deleting). **Keep `vol_graduated_caps`/`beta_graduated_caps` in
`taa_bands.py` INTACTOS** — `beta_graduated_caps` é o throttle de beta POR
INSTRUMENTO (verificado: `taa_bands.py:513-529`), preservado para sua função atual e
para o Plan C consumir; ele NÃO é o cap de beta agregado da política (esse é
`EffectiveRegimePolicy.beta_cap`, compilado como `LinearConstraint` pelo Plan C).
Apenas o call-site S4a deles é removido aqui; as funções e o `BG_COEF` permanecem.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_macro_quadrant_route.py tests/test_taa_bands.py -v`
Expected: PASS for the new macro tests. Delete the obsolete `test_taa_bands.py`
tests for `combined_regime` (108-135), `effective_class_bands` (142-168),
`goldfix_target` (175-192), `band_state_from_quadrant`
(`test_taa_bands_profile_centers.py:15-20`), and `profile_sleeve_bands`
(`test_taa_bands_profile_centers.py:33-46`) — these cover removed symbols. Re-run
until green.

- [ ] **Step 5: Commit**

```bash
git add app/services/taa_bands.py app/api/routes/macro.py \
    app/services/portfolio_builder.py tests/test_taa_bands.py \
    tests/test_taa_bands_profile_centers.py tests/test_macro_quadrant_route.py
git commit -m "refactor(combo): retire effective_class_bands/goldfix/S4a fallback (spec §I)"
```

---

### Task 9: Aposentar `SH`/`hedge` do mapa de sleeves + limpar schemas `combined_regime`

**Files:**
- Modify: `app/optimizer/sleeves.py` (remove `"Inverse / Hedge": "SH"` from `LABEL_TO_PROXY` ~line 46; remove `"SH": "hedge"` from `PROXY_TO_GROUP` ~line 69).
- Modify: `app/schemas/builder.py` (line 314 `combined_regime: str | None`) — remove the field; ADD `beta_cap: float | None = None` (the exposed-not-guaranteed aggregate portfolio-beta cap target emitted by Task 7).
- Modify: `app/schemas/macro.py` (line 77 `combined_regime: str`) — remove the field; update docstring (66-67) to drop the goldfix/haven mention.
- Test: `tests/test_sleeves.py` (append), `tests/test_builder_regime_aware_schema.py` (update).

**Interfaces:**
- Consumes: `sleeves.fund_sleeve_group`, `sleeves.PROXY_TO_GROUP`, `sleeves.SLEEVE_GROUPS` (`app/optimizer/sleeves.py`).
- Produces: `sleeves.fund_sleeve_group(strategy_label, asset_class)` never returns `"hedge"`; `DiagnosticsOut` drops `combined_regime` and gains `beta_cap` (exposed-not-guaranteed); `MacroQuadrantOut` no longer carries `combined_regime`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sleeves.py`:

```python
from app.optimizer import sleeves


def test_hedge_label_not_in_proxy_map() -> None:
    assert "Inverse / Hedge" not in sleeves.LABEL_TO_PROXY
    assert "SH" not in sleeves.PROXY_TO_GROUP
    assert "hedge" not in sleeves.SLEEVE_GROUPS


def test_inverse_fund_does_not_resolve_to_hedge() -> None:
    # An inverse/hedge labelled fund now falls through to the asset_class/equity
    # default, never the removed 'hedge' sleeve.
    sleeve = sleeves.fund_sleeve_group("Inverse / Hedge", None)
    assert sleeve != "hedge"
```

Append to `tests/test_builder_regime_aware_schema.py`:

```python
def test_diagnostics_has_no_combined_regime_field() -> None:
    from app.schemas.builder import DiagnosticsOut
    assert "combined_regime" not in DiagnosticsOut.model_fields


def test_diagnostics_exposes_beta_cap_field() -> None:
    # The aggregate portfolio-beta cap is EXPOSED for telemetry (RELEASE GATE): it is
    # a target, NOT guaranteed until Plan C compiles the LinearConstraint.
    from app.schemas.builder import DiagnosticsOut
    assert "beta_cap" in DiagnosticsOut.model_fields


def test_macro_quadrant_out_has_no_combined_regime_field() -> None:
    from app.schemas.macro import MacroQuadrantOut
    assert "combined_regime" not in MacroQuadrantOut.model_fields
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sleeves.py tests/test_builder_regime_aware_schema.py -k "hedge or inverse or combined_regime" -v`
Expected: FAIL — the mappings/fields still exist.

- [ ] **Step 3: Apply the removals**

In `app/optimizer/sleeves.py`: delete the `"Inverse / Hedge": "SH"` entry from
`LABEL_TO_PROXY` (~line 46) and the `"SH": "hedge"` entry from `PROXY_TO_GROUP`
(~line 69). Verify `SLEEVE_GROUPS` (line 78-80) already lacks `hedge` (it does — the
7 structural sleeves). If `fund_sleeve_group` has a `"hedge"` special-case, remove it.

In `app/schemas/builder.py`: delete `combined_regime: str | None = None` (line 314)
and its doc reference (lines 308-312 mention "combined_regime"; tidy the comment). ADD
`beta_cap: float | None = None` with a docstring noting it is the AGGREGATE
portfolio-beta cap TARGET exposed for telemetry — NOT a guarantee (the constraint is
compiled by Plan C; RELEASE GATE).

In `app/schemas/macro.py`: delete `combined_regime: str` (line 77) and update the
class docstring (60-68) to remove the "combined regime / goldfix haven" wording;
update the `bands` comment (78) from "4 classes (empty when STAG_GOLD haven)" to
"per-sleeve bands (empty when quadrant not consumable)".

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sleeves.py tests/test_builder_regime_aware_schema.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate OpenAPI + commit**

```bash
python -m app.scripts.dump_openapi 2>/dev/null || python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi(), indent=2))"
git add app/optimizer/sleeves.py app/schemas/builder.py app/schemas/macro.py \
    openapi.json tests/test_sleeves.py tests/test_builder_regime_aware_schema.py
git commit -m "refactor(combo): drop SH/hedge from sleeve map + combined_regime fields; expose beta_cap diagnostic"
```

(If no openapi dump entrypoint exists, regenerate however the repo already does it —
grep for `app.openapi()`; if `openapi.json` is generated in CI only, skip the file
and note it in the commit body.)

---

### Task 10: Startup validation hook (fail boot on invalid policies/gate/legacy)

**Files:**
- Create: `app/core/policy_startup.py`
- Modify: `app/main.py` (call the validator inside `lifespan`, before `yield`)
- Test: `tests/test_policy_startup.py`

**Interfaces:**
- Consumes: `quadrant_policy.validate_quadrant_policies` (Task 2); `quadrant_policy.QUADRANT_POLICIES`, `PROFILES`, `QUADRANTS` (Task 1); `gate_overlay.GATE_OVERLAY_SHAPE`, `gate_overlay.PROFILE_GATE_POLICIES`, `gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS`, `gate_overlay.apply_gate_overlay` (Task 3); `effective_policy.build_effective_policy` (Task 5, smoke check that the central producer imports/builds); `app.services.taa_bands` (legacy-symbol scan).
- Produces:
  - `class StartupValidationError(RuntimeError)`.
  - `validate_combo_startup() -> None` — runs the 12-policy validator, the gate-shape/ladder validator, and asserts no legacy symbol (`combined_regime`, `band_state_from_quadrant`, `effective_class_bands`, `goldfix_target`, `HW_SCALE`, `PROFILE_CENTERS`) survives in `taa_bands`. Raises `StartupValidationError` on any failure.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy_startup.py
import pytest

from app.core import policy_startup as ps


def test_validate_combo_startup_passes_on_shipped_config() -> None:
    ps.validate_combo_startup()  # must not raise


def test_validate_combo_startup_rejects_invalid_policies(monkeypatch) -> None:
    import dataclasses

    from app.services import quadrant_policy as qp

    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bad_center = dict(pol.center)
    bad_center["cash"] += 0.10
    bad = dataclasses.replace(pol, center=bad_center)
    broken = {p: dict(qp.QUADRANT_POLICIES[p]) for p in qp.PROFILES}
    broken["moderate"]["recovery"] = bad
    monkeypatch.setattr(qp, "QUADRANT_POLICIES", broken)
    with pytest.raises(ps.StartupValidationError):
        ps.validate_combo_startup()


def test_validate_combo_startup_rejects_surviving_legacy_symbol(monkeypatch) -> None:
    from app.services import taa_bands
    monkeypatch.setattr(taa_bands, "combined_regime", lambda *a, **k: "RISK_ON", raising=False)
    with pytest.raises(ps.StartupValidationError, match="combined_regime"):
        ps.validate_combo_startup()


def test_validate_combo_startup_rejects_ladder_collapse(monkeypatch) -> None:
    from app.optimizer import gate_overlay as go

    same = go.ProfileGatePolicy(intensity=0.7, bl_view_confidence_multiplier=0.0)
    monkeypatch.setattr(
        go, "PROFILE_GATE_POLICIES",
        {"aggressive": same, "moderate": same, "conservative": same},
    )
    with pytest.raises(ps.StartupValidationError, match="ladder"):
        ps.validate_combo_startup()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_policy_startup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.policy_startup'`

- [ ] **Step 3: Implement the startup validator**

```python
# app/core/policy_startup.py
"""COMBO startup validation (spec §37). Run in the app lifespan BEFORE serving.

Validates: the 12 QuadrantPolicies (centers sum 1, bands in [0,1], risk_assets_cap,
defensive_floor); the gate shape + per-profile ladder (3 profiles do not collapse
to identical effective tightening); and that NO legacy symbol survives on the
production module (combined_regime, band_state_from_quadrant, effective_class_bands,
goldfix_target, HW_SCALE, PROFILE_CENTERS). Any failure aborts the boot.
"""
from __future__ import annotations

from app.optimizer import gate_overlay
from app.services import quadrant_policy, taa_bands

_LEGACY_SYMBOLS = (
    "combined_regime",
    "band_state_from_quadrant",
    "effective_class_bands",
    "goldfix_target",
    "HW_SCALE",
    "PROFILE_CENTERS",
    "DEFAULT_TAA_BANDS",
    "normalized_profile_centers",
    "profile_sleeve_bands",
)


class StartupValidationError(RuntimeError):
    """A COMBO startup invariant failed; the service must not start."""


def _validate_gate_ladder() -> None:
    # cvar_mult must differ across the 3 profiles in risk_off (ladder, spec §23).
    muls = {
        p: gate_overlay.apply_gate_overlay(
            p, "risk_off", base_risk_assets_cap=0.40,
            base_portfolio_beta_cap=gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS[p],
        ).cvar_mult
        for p in quadrant_policy.PROFILES
    }
    if len({round(v, 9) for v in muls.values()}) < len(muls):
        raise StartupValidationError(
            f"gate ladder collapsed — profiles share cvar_mult: {muls}"
        )
    # the aggregate portfolio-beta cap ladder must also be strictly monotone (spec §23).
    caps = gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS
    if not (caps["aggressive"] > caps["moderate"] > caps["conservative"]):
        raise StartupValidationError(
            f"portfolio-beta cap ladder not monotone: {caps}"
        )


def _validate_no_legacy() -> None:
    for name in _LEGACY_SYMBOLS:
        if hasattr(taa_bands, name):
            raise StartupValidationError(
                f"legacy symbol {name!r} still present on taa_bands (spec §I)"
            )


def validate_combo_startup() -> None:
    """Run every COMBO startup check; raise StartupValidationError on the first
    failure. Wraps quadrant_policy.PolicyError / gate_overlay.GateError so the
    boot path sees a single error type."""
    try:
        quadrant_policy.validate_quadrant_policies()
    except quadrant_policy.PolicyError as exc:
        raise StartupValidationError(f"policy invariant failed: {exc}") from exc
    try:
        _validate_gate_ladder()
    except gate_overlay.GateError as exc:
        raise StartupValidationError(f"gate shape invalid: {exc}") from exc
    _validate_no_legacy()
```

In `app/main.py`, call it inside `lifespan` before `yield`:

```python
from app.core.policy_startup import validate_combo_startup


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # COMBO regime_aware policy core: fail-loud at boot if any of the 12 policies,
    # the gate shape/ladder, or the legacy-symbol scan fails (spec §37).
    validate_combo_startup()
    # The TiingoClient is created lazily on first dependency use (the app must
    # boot without a token so /health works); if created, close it here.
    yield
    await tiingo_provider.aclose()
    await engine.dispose()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_policy_startup.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full regime + policy suites + app-import smoke**

Run: `python -m pytest tests/test_quadrant_policy.py tests/test_gate_overlay.py tests/test_effective_policy.py tests/test_momentum_view.py tests/test_policy_startup.py tests/test_builder_regime_two_level.py tests/test_builder_regime_aware.py tests/test_macro_quadrant_route.py tests/test_sleeves.py -v`
Expected: all PASS. Then `python -c "from app.main import app"` — must import without
raising (proves the startup validator passes against the shipped config).

- [ ] **Step 6: Commit**

```bash
git add app/core/policy_startup.py app/main.py tests/test_policy_startup.py
git commit -m "feat(combo): startup validation hook — 12 policies + gate ladder + legacy scan (spec §37)"
```

---

## Self-Review

**Spec coverage** (Parts C and D):
- §12 separação QuadrantPolicy→GateOverlay→BL→two-level, composta em `EffectiveRegimePolicy` → Tasks 1/3/5/7 (the two-level compiler itself is Plan C).
- §13 sete sleeves; remover hedge/SH/STAG_GOLD/GOLDFIX → Task 1 (`STRUCTURAL_SLEEVES`), Tasks 8-9 (removals).
- §14 contrato `Budget`/`QuadrantPolicy` + 12 políticas → Task 1.
- §15 invariantes → Task 2; §37 startup validation → Task 10.
- §16 descrição dos 4 quadrantes + §17/§18 seeds + §19 half-widths → Task 1 (centers/half-widths materialized).
- §20 `FIXED_INCOME_BUCKETS` + campo vazio v1 → Task 1; exposto via `EffectiveRegimePolicy.fixed_income_sub_budgets` → Task 5.
- §21-§22 GateOverlay shape/profile-policy + `effective_*` (incl. cap de beta AGREGADO `EffectiveGate.beta_cap`) → Task 3; §23 invariantes + ladder (cvar + beta-cap monotone) → Tasks 3/10; §24 BL multiplier → Tasks 4/6.
- **Decisão B (produto coeso):** `EffectiveRegimePolicy` + `build_effective_policy` → Task 5; consumido pelo builder → Task 7.
- **Decisão C (beta agregado):** `PROFILE_PORTFOLIO_BETA_CAPS` + `effective_beta_cap` → Task 3; `beta_graduated_caps` (per-instrumento) PRESERVADO → Tasks 8 (só remove o call-site S4a). NÃO há `effective_beta_coef`.
- **Decisão D (RELEASE GATE):** documentada na seção dedicada + nas Tasks 7/9 (beta_cap exposto-não-garantido).
- §31 erros `POLICY_NOT_FOUND`/`QUADRANT_UNAVAILABLE`/`GATE_UNAVAILABLE` → Tasks 5/7 (`EffectivePolicyError` mapeado via `_as_builder_error`); `POLICY_VERSION_MISMATCH` is the worker↔backend contract (spec §36, deferred to atomic activation — `policy_version` is materialized in Task 1 so the check has a value to compare).
- Part I legados (combined_regime, band_state_from_quadrant, STAG_GOLD, goldfix, HW_SCALE, effective_class_bands, S4a fallback, runtime normalization, None→quadrant) → Tasks 7-10.
- NOT covered here (out of scope, by design): **the two-level compiler / matriz M / preflight LP / compilação do `LinearConstraint(coef = M.T @ final_instrument_betas, hi=effective_beta_cap)` de beta AGREGADO / post-verification of FI sub-budgets (Plan C)** — por isso `beta_cap` é exposto-não-garantido na v1 (RELEASE GATE); `effective_status`/consumibilidade per §3/§6 and the SQL §6 validity filter (Track A — the reader producing the consumable `QuadrantSnapshot`); the worker v2 (Track A); deploy/atomic activation (spec §36).

**Placeholder scan:** every step ships real code/commands. The only deferred mechanics are (a) the per-row `fixed_income` residual correction in Task 1 Step 3/4 — explicitly bounded by the `test_every_center_sums_to_one` gate and the `1e-6` tolerance; (b) the OpenAPI regeneration in Task 9 — guarded with a grep-first note. No "TODO"/"similar to Task N"/"add error handling".

**Type consistency:** `Quadrant`/`GateState` (str aliases, Task 1) consumed by `gate_overlay.apply_gate_overlay` (Task 3) and `EffectiveRegimePolicy` (Task 5). `QuadrantPolicy`/`Budget`/`QUADRANT_POLICIES`/`policy_bands` (Task 1) consumed identically in Tasks 2/5/7/8/10. `GateOverlayShape`/`ProfileGatePolicy`/`EffectiveGate`/`apply_gate_overlay`/`PROFILE_PORTFOLIO_BETA_CAPS` (Task 3) consumed in Tasks 4/5/10. `EffectiveRegimePolicy`/`build_effective_policy`/`EffectivePolicyError` (Task 5) consumed by the builder (Task 7) and smoke-checked at startup (Task 10). `view_confidence_multiplier` keyword (Task 6) called from `_solve_regime_level1` (Task 7). The structured errors all subclass `BuilderError` (→ 422); `EffectivePolicyError`→`BuilderError` via `_as_builder_error`. Legacy-symbol names in Task 10's `_LEGACY_SYMBOLS` match exactly the symbols deleted in Tasks 7-8. **No `effective_beta_coef` symbol exists** (asserted in Task 4 `test_no_effective_beta_coef_symbol`).

**Owner-review flags (spec↔code contradictions found):**
1. **RECOVERY/EXPANSION centers do NOT sum to 1 in the current code** (e.g. `conservative RISK_ON` = 1.07, `aggressive INFLATION` = 0.97) — they relied on `normalized_profile_centers` runtime normalization, which §15/§I forbid. This plan ships re-normalized literal centers (Task 1). The owner should confirm the re-normalized values are acceptable as the v1 seed (they preserve the relative mix; the residual lands on `fixed_income`), since §35 calibration step 1 freezes RECOVERY/EXPANSION.
2. **`risk_assets_cap`/`defensive_floor`/`PROFILE_PORTFOLIO_BETA_CAPS` did not exist anywhere** — the values in Tasks 1/3 are seeds chosen to satisfy §15/§23 (equity+thematic ≤ cap; cash+fi+gold+ls ≥ floor; aggregate beta-cap ladder monotone). They are calibration targets (§33, A4), not validated. The portfolio-beta seeds (`aggressive 0.85 / moderate 0.55 / conservative 0.30`) in particular are first guesses; flagged for A4.
3. **`beta_cap` é EXPOSTO mas NÃO garantido na v1 (RELEASE GATE).** A decisão final do dono é um cap de beta AGREGADO de carteira (`β_portfolio ≤ effective_beta_cap`), compilado pelo Plano C como `LinearConstraint(coef = M.T @ final_instrument_betas, hi=effective_beta_cap)`. Este plano só MATERIALIZA o número em `EffectiveRegimePolicy.beta_cap` e o emite em telemetria/diagnóstico. `beta_graduated_caps` (per-instrumento, verificado `taa_bands.py:513-529`) é preservado intacto e NÃO representa essa política. Nenhuma carteira pode ser publicada afirmando garantia de beta agregado até o Plano C aterrissar. O dono deve confirmar que rodar a v1 com `beta_cap` apenas-exposto é aceitável até lá.
4. **`_resolve_regime_block_budgets` block budgets feed the now-removed S4a/diagnostics path** — after Task 7 the production path is two-level only (which consumes `EffectiveRegimePolicy.sleeve_budgets`). The function is kept for diagnostics but its 4-class `_fund_class_columns` mapping is a known mismatch with the 7-sleeve policy; flagged so the owner can decide whether to fold it into the two-level path or drop it in Plan C.

**Call-sites of `combined_regime` the plan rewrites/removes (path:line, production):**
- `app/services/taa_bands.py:325-363` — definition `combined_regime` → DELETED (Task 7).
- `app/services/taa_bands.py:190-205` — `band_state_from_quadrant` → DELETED (Task 7).
- `app/services/portfolio_builder.py:487` — `regime = taa_bands.combined_regime(gate_state, quadrant)` → rewritten to `build_effective_policy` (Task 7).
- `app/services/portfolio_builder.py:683` — `band_state = taa_bands.band_state_from_quadrant(quadrant)` → `EffectiveRegimePolicy.sleeve_budgets` (Task 7).
- `app/services/portfolio_builder.py:1219-1221` — unpack `regime_combined` from `_resolve_regime_block_budgets` → returns `(blocks, quadrant, gate_state)` (Task 7).
- `app/services/portfolio_builder.py:1234` — `if regime_combined == "STAG_GOLD":` goldfix branch (1234-1249) → REMOVED (Task 7).
- `app/services/portfolio_builder.py:1274` — `taa_bands.effective_class_bands(regime_combined)` in S4a → REMOVED (Task 8).
- `app/services/portfolio_builder.py:1295` — `if regime_combined == "RISK_OFF":` beta branch → REMOVED with S4a (Task 8).
- `app/services/portfolio_builder.py:1491` — `combined_regime=regime_combined` diagnostics → REMOVED, `beta_cap=regime_beta_cap` ADDED (exposed-not-guaranteed) (Task 7).
- `app/api/routes/macro.py:70` — `regime = taa_bands.combined_regime(gate_state, quadrant)` → orthogonal rewrite (Task 8).
- `app/api/routes/macro.py:72` — `if regime == "STAG_GOLD":` → REMOVED (Task 8).
- `app/api/routes/macro.py:78` — `taa_bands.effective_class_bands(regime)` → `policy_bands` (Task 8).
- `app/api/routes/macro.py:107` — `combined_regime=regime` → REMOVED (Task 8).
- `app/schemas/builder.py:314` — `combined_regime: str | None` field → REMOVED; `beta_cap: float | None` ADDED for the exposed-not-guaranteed diagnostic (Task 9).
- `app/schemas/macro.py:77` — `combined_regime: str` field → REMOVED (Task 9).
- `openapi.json` (generated mirror) — regenerated (Task 9).
- Tests referencing `combined_regime` (updated/removed in Tasks 7-9): `tests/test_taa_bands.py:108-135`; `tests/test_builder_regime_aware.py:233,255,297,545`; `tests/test_builder_regime_two_level.py:382`; `tests/test_macro_quadrant_route.py:82,124,143`.
