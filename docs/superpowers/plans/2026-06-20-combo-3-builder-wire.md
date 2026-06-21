> SUPERSEDED by docs/superpowers/plans/2026-06-21-combo-*.md (see 2026-06-21 spec)

# COMBO Componente 3 — Wire no otimizador/builder (objetivo `combo`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Um novo objetivo `"combo"` no builder que (a) lê o composite + quadrante macro, (b) chama `taa_bands.effective_class_bands` para obter `(min,max)` por classe, (c) converte em `engine.BlockBudget` por classe, (d) resolve a CVaR DENTRO dessa envoltória; e que troca a leitura de regime do CVaR-scaling de credit-only → composite.

**Architecture:** O engine JÁ honra `blocks=`/`linear=` em todos os solvers (`BlockBudget`, `engine.py:234`; `BoundsBundle`, `engine.py:345`). O `_resolve_block_budgets` (`portfolio_builder.py:233`) já mapeia classe→índices. COMBO reusa essa maquinaria: gera os `BlockBudget` a partir das bandas do regime (em vez de `block_budgets` do payload) e despacha para o solver de CVaR `max_return_cvar`/`min_cvar`. A leitura de regime do scaling (`fetch_credit_regime`, `portfolio_builder.py:703`) passa a `fetch_composite_regime`.

**Tech Stack:** cvxpy/CLARABEL, SQLAlchemy async, Pydantic v2, FastAPI, pytest.

## Global Constraints
- Repo: `E:/investintell-light/backend`.
- Engine inalterado: NÃO modificar `engine.py` (já tem `BlockBudget`/`BoundsBundle`/`linear`). Apenas consumir.
- COMBO = CVaR objective DENTRO das bandas do regime. Objetivo base da CVaR: usar o caminho `max_return_cvar` (equilíbrio sem views; é o objetivo primário do redesign do builder) quando não houver views; se o owner preferir `min_cvar`, é trocar o solver alvo (documentado). Default deste plano: `max_return_cvar`.
- Bandas vêm de `taa_bands.effective_class_bands(combined_regime(composite_state, quadrant))` (Componente 2). `hw_scale=1.5`.
- `multi_asset` NÃO recebe BlockBudget (spec O3); classes ausentes do universo final são puladas (mesmo comportamento de `_resolve_block_budgets`).
- Troca credit→composite vale para o scaling da CVaR também (`regime_cvar_multiplier`, `portfolio_builder.py:109`, aceita `state` do composite — `"risk_off"`).
- Vale em modo explícito E amplo (no amplo, sobre os representantes selecionados).
- TDD; comando: `cd backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -v`. Há um seam de teste de regime (`_OVERRIDE_REGIME_STATE`, ver `portfolio_builder.py:700`) — usar/estender análogo para o quadrante.

---

### Task 1: Objetivo `combo` no schema

**Files:**
- Modify: `backend/app/schemas/builder.py` (`Objective` Literal, `builder.py:65-68`)
- Test: `backend/tests/test_builder_combo_schema.py`

**Interfaces:**
- Produces: `Objective` ganha `"combo"`: `Literal["equal_weight","min_vol","erc","max_diversification","min_cvar","bl_utility","max_return_cvar","combo"]`. `OptimizeRequest` aceita `objective="combo"`. Nenhum campo novo obrigatório (as bandas são derivadas do regime, não do payload).

- [ ] **Step 1: Teste falhando**:

```python
from app.schemas.builder import OptimizeRequest


def test_combo_is_valid_objective():
    req = OptimizeRequest.model_validate({
        "assets": [{"instrument_id": 1}, {"instrument_id": 2}],
        "objective": "combo",
    })
    assert req.objective == "combo"
```

(Ajustar o shape de `AssetRefIn` ao real — ver `builder.py` `AssetRefIn` — durante a escrita; o ponto é validar que `"combo"` é aceito.)

- [ ] **Step 2: Rodar e ver falhar** — `cd backend && .venv/Scripts/python -m pytest tests/test_builder_combo_schema.py -v` (ValidationError: `combo` não permitido).
- [ ] **Step 3: Implementar** — adicionar `"combo"` ao Literal `Objective`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/schemas/builder.py backend/tests/test_builder_combo_schema.py && git commit -m "Add combo objective to builder schema"`.

---

### Task 2: Bandas do regime → BlockBudgets no builder

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (nova função privada + ramo `combo` no dispatch de objetivo, ~`portfolio_builder.py:682-763`)
- Test: `backend/tests/test_builder_combo.py`

**Interfaces:**
- Consumes: `taa_bands.combined_regime`, `taa_bands.effective_class_bands` (Componente 2); `taa_bands.fetch_macro_quadrant` + `macro_regime.fetch_composite_regime`; `_resolve_block_budgets`-style mapeamento classe→índices (reusar a lógica de mapeamento de `_resolve_block_budgets`, `portfolio_builder.py:233`, que já resolve `asset_class` por fundo e falha-alto p/ ações sem classe); `engine.BlockBudget`.
- Produces:
  - `async def _resolve_regime_block_budgets(session, datalake, assets, labels) -> tuple[list[engine.BlockBudget], str, "MacroQuadrantSnapshot | None", "str"]` — lê composite (`fetch_composite_regime`) e quadrante (`fetch_macro_quadrant`); `regime = combined_regime(composite.state, quad.quadrant)`; `bands = effective_class_bands(regime)`; para cada classe em `{equity,fixed_income,alternatives,cash}` presente no universo, monta `BlockBudget(indices=<cols da classe>, lo=band_lo, hi=band_hi)`. `multi_asset` e classes ausentes: puladas. Retorna `(blocks, regime, quad, composite_state)`.
  - Reaproveitar o mecanismo de resolução de classe por coluna que `_resolve_block_budgets` já usa (NÃO reimplementar a descoberta de `asset_class`; extrair/compartilhar um helper se preciso).

- [ ] **Step 1: Testes falhando** (com monkeypatch dos readers + dados sintéticos, no estilo de `tests/test_builder_block_budgets.py`):

```python
# Pseudocódigo-guia; alinhar aos seams reais (load_aligned_returns,
# load_fund_asset_class, fetch_composite_regime, fetch_macro_quadrant).
import pytest
from app.services import portfolio_builder as pb
from app.services import taa_bands as tb


@pytest.mark.asyncio
async def test_combo_builds_regime_blocks(monkeypatch):
    # Force RISK_ON via composite risk_on + quadrant RECOVERY
    monkeypatch.setattr(pb.macro_regime, "fetch_composite_regime",
                        _async_ret(_snap(state="risk_on")))
    monkeypatch.setattr(pb.taa_bands, "fetch_macro_quadrant",
                        _async_ret(_quad("RECOVERY")))
    blocks, regime, quad, comp = await pb._resolve_regime_block_budgets(
        session, datalake, assets, labels)
    assert regime == "RISK_ON"
    # equity band under RISK_ON hw 1.5 => [0.40, 0.64]
    eq = next(b for b in blocks if _is_equity(b, labels))
    assert abs(eq.lo - 0.40) < 1e-9 and abs(eq.hi - 0.64) < 1e-9
```

- [ ] **Step 2: Rodar e ver falhar** — `... pytest tests/test_builder_combo.py -k regime_blocks -v`.
- [ ] **Step 3: Implementar** `_resolve_regime_block_budgets` reusando o mapeamento classe→índices existente.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/services/portfolio_builder.py backend/tests/test_builder_combo.py && git commit -m "Derive regime BlockBudgets from taa_bands in builder"`.

---

### Task 3: Dispatch do objetivo `combo` (CVaR dentro das bandas) + integração end-to-end

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (`run_optimize`, ramo `combo` no dispatch ~`portfolio_builder.py:682-763`)
- Test: `backend/tests/test_builder_combo.py`

**Interfaces:**
- Consumes: `_resolve_regime_block_budgets` (Task 2); `engine.solve_max_return_cvar_capped` (`engine.py:979`) com `bounds=BoundsBundle(blocks=...)`; `apply_regime_cvar_limit`/`regime_cvar_multiplier` (`portfolio_builder.py:109-123`).
- Produces: no `run_optimize`, `elif payload.objective == "combo":` — resolve blocks do regime; monta `BoundsBundle(cap_vec, min_vec, blocks=regime_blocks)`; aplica `cvar_limit_effective = apply_regime_cvar_limit(base, composite_state, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR)`; chama `solve_max_return_cvar_capped(..., bounds=cvar_bounds)`; popula o resultado com `regime`, `quadrant`, e as bandas resultantes (para o frontend exibir). A resposta de optimize deve carregar o regime/quadrante/bandas usados (adicionar campos opcionais no schema de resposta de optimize — `OptimizeResponse` em `builder.py`).

**Comportamento:** Quando `combo`, IGNORAR `constraints.block_budgets` do payload (as bandas vêm do regime) — documentar; demais constraints (`cap`, `overlap_cap`) continuam valendo (overlap via `linear`, se setado, segue o caminho do Sprint B). Vale em modo amplo (representantes selecionados).

- [ ] **Step 1: Teste falhando (end-to-end via rota)** — universo com 2 ações de equity e 1 fundo de fixed_income; forçar regime RISK_OFF (composite risk_off); `POST /builder/optimize` com `objective="combo"`; afirmar que a soma de pesos de equity ≤ `hi` da banda RISK_OFF de equity (`0.38+0.08*1.5=0.50`) e ≥ `lo` (`0.38-0.12=0.26`), e que a resposta traz `regime=="RISK_OFF"`. Controle: `objective="max_return_cvar"` sem bandas pode passar de 0.50.

```python
@pytest.mark.asyncio
async def test_combo_endpoint_respects_riskoff_equity_band(monkeypatch, client):
    monkeypatch.setattr(pb.macro_regime, "fetch_composite_regime",
                        _async_ret(_snap(state="risk_off")))
    monkeypatch.setattr(pb.taa_bands, "fetch_macro_quadrant",
                        _async_ret(_quad("CONTRACTION")))
    # monkeypatch returns/class loaders as in test_builder_block_budgets.py
    resp = await client.post("/builder/optimize", json={
        "assets": [...], "objective": "combo"})
    body = resp.json()
    assert body["regime"] == "RISK_OFF"
    eq_sum = sum(w for a, w in body["weights"].items() if _is_eq(a))
    assert eq_sum <= 0.50 + 1e-6
    assert eq_sum >= 0.26 - 1e-6
```

- [ ] **Step 2: Rodar e ver falhar** — `... pytest tests/test_builder_combo.py -k endpoint -v`.
- [ ] **Step 3: Implementar** o ramo `combo` no dispatch + campos `regime`/`quadrant`/`bands` no `OptimizeResponse`.
- [ ] **Step 4: Rodar e ver passar** + suite do builder sem regressão (`... pytest tests/ -k builder -q`).
- [ ] **Step 5: Commit** — `git add backend/app/services/portfolio_builder.py backend/app/schemas/builder.py backend/tests/test_builder_combo.py && git commit -m "Wire combo objective: CVaR within regime bands"`.

---

### Task 4: Trocar credit-only → composite no CVaR-scaling

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (`portfolio_builder.py:700-708` — a leitura de regime que escala a CVaR)
- Test: `backend/tests/test_builder_regime_scaling.py` (novo) ou estender o teste existente do scaling

**Interfaces:**
- Consumes: `macro_regime.fetch_composite_regime` (em vez de `fetch_credit_regime`).
- Produces: o caminho de scaling da CVaR (válido para `max_return_cvar` e `combo`) lê `fetch_composite_regime(datalake).state` em vez de `fetch_credit_regime`. `regime_cvar_multiplier` é inalterado (já compara `state == "risk_off"`, compatível com o composite). Manter o seam `_OVERRIDE_REGIME_STATE` funcionando.

**Investigação obrigatória (implementer):** confirmar que `fetch_composite_regime` retorna `state` na mesma convenção (`"risk_off"`) que `regime_cvar_multiplier` espera (ver `macro_regime.py:117` `CompositeRegimeSnapshot.state` e `portfolio_builder.py:109`). Se o composite usar `"RISK_OFF"` (maiúsculo), normalizar.

- [ ] **Step 1: Teste falhando** — com `fetch_composite_regime` mockado em `risk_off`, o `cvar_limit_effective` aplicado é `base * DEFAULT_RISK_OFF_CVAR_FACTOR`; com `risk_on`, é `base`. Verificar via um seam observável (campo `cvar_limit_effective` na resposta, ou via spy no `apply_regime_cvar_limit`).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** a troca de `fetch_credit_regime` → `fetch_composite_regime` (com normalização de caixa se necessário).
- [ ] **Step 4: Rodar e ver passar** + garantir que os testes existentes de `max_return_cvar`/regime não regridam (ajustar mocks que apontavam para `fetch_credit_regime`).
- [ ] **Step 5: Commit** — `git add backend/app/services/portfolio_builder.py backend/tests/test_builder_regime_scaling.py && git commit -m "Switch CVaR-scaling regime read from credit-only to composite"`.

---

## Self-Review (cobertura do spec §4.3 / §5 componente 3)
- Objetivo `combo` no schema → Task 1.
- Bandas do regime → BlockBudgets (reuso de `_resolve_block_budgets` e `BlockBudget`) → Task 2.
- Dispatch `combo` (CVaR dentro das bandas) + regime/quadrante/bandas na resposta → Task 3.
- Troca credit→composite no scaling → Task 4.
- `multi_asset` sem banda (O3) e `block_budgets` do payload ignorados no combo: documentados nos Global Constraints/Task 3.
- Modo amplo coberto (representantes selecionados) → Task 3 Comportamento.
- Consistência de tipos: `effective_class_bands` (dict→(min,max)) → `BlockBudget(indices,lo,hi)` → `BoundsBundle(blocks=...)` → `solve_max_return_cvar_capped`.
