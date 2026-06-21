> SUPERSEDED by docs/superpowers/plans/2026-06-21-combo-*.md (see 2026-06-21 spec)

# COMBO Componente 4 — Macro page (quadrante macro + bandas) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Dirigir o quadrante growth×inflation existente (Recovery/Expansion/Slowdown/Contraction) na página Macro com os NOVOS fatores growth/inflation (do `macro_factor_daily`), e exibir o quadrante atual + as bandas por classe resultantes.

**Architecture:** O backend `/macro/regime` (`MacroRegimeResponse`, `backend/app/api/routes/macro.py:42`) ganha um bloco `macro_quadrant` (quadrante atual + growth/inflation scores/states + bandas por classe do regime COMBO). O frontend regenera tipos (`pnpm run types`), o client `fetchMacroRegime` (`frontend/src/lib/api/client.ts:1423`) passa a expor o bloco, e `MacroRegimeView` (`frontend/src/components/macro/MacroRegimeView.tsx`) exibe o quadrante atual e um painel de bandas (padrão de `buildHcDriftBandsOption`, `frontend/src/lib/charts/hc/rebalance.ts`, + enumeração de classes de `PortfolioConstraintsSection.tsx`).

**Tech Stack:** Next.js/React Query, Highcharts 13, vitest+jsdom, openapi-typescript. Backend FastAPI/Pydantic.

## Global Constraints
- Repos: `E:/investintell-light/backend` (resposta da rota) e `frontend`.
- Reusar a infra existente: o quadrante já é renderizado por `buildHcMacroRrgOption` (`frontend/src/lib/charts/hc/macro-rrg.ts`) e a página por `MacroRegimeView`. NÃO recriar a página.
- Bandas exibidas = as 4 classes `equity/fixed_income/alternatives/cash` (sem `multi_asset`).
- Cores via tokens (`chartColors()`, `frontend/src/lib/charts/chartColors.ts`) — sem hex hardcoded.
- Tipos gerados: `frontend/src/lib/api/api.d.ts` via `pnpm run types` (lê `backend/openapi.json`; exportar com `scripts/export_openapi.py` se for o fluxo do projeto).
- TDD: vitest para os builders puros e para o componente; backend pytest para o schema da resposta.
- Comandos: backend `cd backend && .venv/Scripts/python -m pytest`; frontend `cd frontend && pnpm test`, `pnpm run typecheck`, `pnpm run types`, `pnpm build`.

---

### Task 1: Backend — bloco `macro_quadrant` na resposta `/macro/regime`

**Files:**
- Modify: `backend/app/schemas/macro.py` (`MacroRegimeResponse` + novo sub-schema `MacroQuadrantOut`)
- Modify: `backend/app/api/routes/macro.py` (`get_macro_regime`, `macro.py:42-97`)
- Test: `backend/tests/test_macro_quadrant_route.py`

**Interfaces:**
- Consumes: `taa_bands.fetch_macro_quadrant` + `macro_regime.fetch_composite_regime` + `taa_bands.combined_regime`/`effective_class_bands` (Componente 2).
- Produces: `MacroQuadrantOut`:

```python
class ClassBandOut(BaseModel):
    asset_class: str
    min_weight: float
    max_weight: float

class MacroQuadrantOut(BaseModel):
    as_of: date | None
    quadrant: str | None             # RECOVERY|EXPANSION|SLOWDOWN|CONTRACTION
    growth_state: str | None         # up|down
    inflation_state: str | None
    growth_score: float | None
    inflation_score: float | None
    regime: str                      # RISK_ON|RISK_OFF|INFLATION (combined)
    bands: list[ClassBandOut]
```

`MacroRegimeResponse` ganha `macro_quadrant: MacroQuadrantOut | None = None`. O handler: lê composite + quadrante; `regime = combined_regime(composite.state, quad.quadrant if quad else None)`; `bands = effective_class_bands(regime)`; monta `MacroQuadrantOut`. Se `macro_factor_daily` ainda vazia, `quadrant=None` mas ainda devolve `regime`/`bands` (regime derivado só do composite → RISK_ON/RISK_OFF).

- [ ] **Step 1: Teste falhando** — com readers mockados (composite risk_on + quadrante EXPANSION), `GET /macro/regime` retorna `macro_quadrant.quadrant=="EXPANSION"`, `regime=="INFLATION"`, e `bands` contém as 4 classes com a banda de equity de INFLATION (`center .42 hw .08*1.5=.12 -> [.30,.54]`).

```python
@pytest.mark.asyncio
async def test_macro_regime_includes_quadrant(monkeypatch, client):
    # override datalake-backed readers used by the macro route
    ...
    resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    assert mq["quadrant"] == "EXPANSION"
    assert mq["regime"] == "INFLATION"
    eq = next(b for b in mq["bands"] if b["asset_class"] == "equity")
    assert abs(eq["min_weight"] - 0.30) < 1e-6
    assert abs(eq["max_weight"] - 0.54) < 1e-6
```

- [ ] **Step 2: Rodar e ver falhar** — `cd backend && .venv/Scripts/python -m pytest tests/test_macro_quadrant_route.py -v`.
- [ ] **Step 3: Implementar** o sub-schema + montagem no handler.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/schemas/macro.py backend/app/api/routes/macro.py backend/tests/test_macro_quadrant_route.py && git commit -m "Expose macro_quadrant (quadrant + regime bands) on /macro/regime"`.

---

### Task 2: Regenerar tipos do frontend + client

**Files:**
- Regenerate: `backend/openapi.json` (via `scripts/export_openapi.py` se for o fluxo) → `frontend/src/lib/api/api.d.ts` (`pnpm run types`)
- Modify: `frontend/src/lib/api/client.ts` (re-exportar o tipo `MacroQuadrant` derivado de `MacroRegimeResponse.macro_quadrant`; `fetchMacroRegime` já retorna `MacroRegime` — só garantir o novo campo)
- Test: `frontend/src/lib/api/client.macro.test.ts` (smoke do tipo/fetch, opcional se já houver cobertura)

**Interfaces:**
- Consumes: `MacroRegimeResponse` atualizado (Task 1).
- Produces: `export type MacroQuadrant = MacroRegime["macro_quadrant"]` (ou via `components["schemas"]["MacroQuadrantOut"]`) em `client.ts`, para o componente consumir tipado.

- [ ] **Step 1:** Rodar `cd backend && .venv/Scripts/python scripts/export_openapi.py` (ou o comando real do projeto) para atualizar `backend/openapi.json`; depois `cd frontend && pnpm run types`. Confirmar que `MacroQuadrantOut`/`macro_quadrant` aparecem em `api.d.ts`.
- [ ] **Step 2:** Adicionar `export type MacroQuadrant = ...` em `client.ts` e (se aplicável) ajustar o tipo de retorno de `fetchMacroRegime`.
- [ ] **Step 3:** `pnpm run typecheck` verde.
- [ ] **Step 4: Commit** — `git add backend/openapi.json frontend/src/lib/api/api.d.ts frontend/src/lib/api/client.ts && git commit -m "Regenerate types for macro_quadrant; export MacroQuadrant"`.

---

### Task 3: Builder de gráfico das bandas por classe

**Files:**
- Create: `frontend/src/lib/charts/hc/macro-bands.ts`
- Test: `frontend/src/lib/charts/hc/macro-bands.test.ts`

**Interfaces:**
- Consumes: `ChartColors` (`chartColors()`), o array `bands` do `macro_quadrant`.
- Produces: `export function buildHcMacroBandsOption(bands: { asset_class: string; min_weight: number; max_weight: number }[], colors: ChartColors): Options | null` — barra horizontal por classe mostrando o intervalo `[min,max]` (usar `columnrange` ou `plotBands`/range bars; espelhar o padrão de `buildHcDriftBandsOption` em `rebalance.ts`). `null` se `bands` vazio. Cores dos tokens; rótulos com as 4 classes na ordem `equity, fixed_income, alternatives, cash`.

- [ ] **Step 1: Teste falhando** (vitest, sem jsdom — builder puro; usar fixture `TEST_COLORS` de `src/lib/charts/hc/__fixtures__/colors`):

```ts
import { describe, it, expect } from "vitest";
import { buildHcMacroBandsOption } from "./macro-bands";
import { TEST_COLORS } from "./__fixtures__/colors";

describe("buildHcMacroBandsOption", () => {
  it("returns null for empty bands", () => {
    expect(buildHcMacroBandsOption([], TEST_COLORS)).toBeNull();
  });

  it("emits one range per class with min/max extent", () => {
    const opt = buildHcMacroBandsOption([
      { asset_class: "equity", min_weight: 0.4, max_weight: 0.64 },
      { asset_class: "cash", min_weight: 0.03, max_weight: 0.105 },
    ], TEST_COLORS)!;
    const data = (opt.series?.[0] as any).data;
    expect(data).toHaveLength(2);
    expect(data[0]).toEqual(expect.arrayContaining([0.4, 0.64]));
  });

  it("orders classes equity, fixed_income, alternatives, cash", () => {
    const opt = buildHcMacroBandsOption([
      { asset_class: "cash", min_weight: 0, max_weight: 0.1 },
      { asset_class: "equity", min_weight: 0.4, max_weight: 0.6 },
    ], TEST_COLORS)!;
    const cats = (opt.xAxis as any).categories;
    expect(cats.indexOf("equity")).toBeLessThan(cats.indexOf("cash"));
  });
});
```

- [ ] **Step 2: Rodar e ver falhar** — `cd frontend && pnpm test src/lib/charts/hc/macro-bands.test.ts`.
- [ ] **Step 3: Implementar** `buildHcMacroBandsOption` (columnrange horizontal; ordenação canônica das classes; cores via tokens).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add frontend/src/lib/charts/hc/macro-bands.ts frontend/src/lib/charts/hc/macro-bands.test.ts && git commit -m "Add macro per-class bands chart builder"`.

---

### Task 4: Exibir quadrante atual + bandas no `MacroRegimeView`

**Files:**
- Modify: `frontend/src/components/macro/MacroRegimeView.tsx`
- Test: `frontend/src/components/macro/MacroRegimeView.quadrant.test.tsx` (jsdom)

**Interfaces:**
- Consumes: `MacroRegime.macro_quadrant` (Task 2), `buildHcMacroBandsOption` (Task 3), `HighchartsChart` (`frontend/src/components/charts/HighchartsChart.tsx`).
- Produces: uma seção nova em `MacroRegimeView` que, quando `macro_quadrant` está presente: mostra o rótulo do quadrante atual (RECOVERY/EXPANSION/SLOWDOWN/CONTRACTION), os estados/escores growth & inflation, o `regime` combinado, e o gráfico de bandas (`<HighchartsChart options={buildHcMacroBandsOption(macro_quadrant.bands, colors)} />`). Se `macro_quadrant` ausente (tabela vazia), seção exibe um empty-state discreto.

**Investigação obrigatória (implementer):** ver como `MacroRegimeView` já obtém `colors` (provável `chartColors()` em `useMemo` pós-mount) e como compõe os blocos atuais (o RRG em `h-[440px]`); inserir a seção próxima ao quadrante RRG para coesão visual. NÃO mexer no `buildHcMacroRrgOption` existente (o RRG continua; a nova seção é complementar e mostra o quadrante DERIVADO dos novos fatores + as bandas).

- [ ] **Step 1: Teste falhando** (jsdom; mock de `fetchMacroRegime` devolvendo `macro_quadrant` com `quadrant:"EXPANSION"`, `regime:"INFLATION"`, 4 bandas): renderiza o texto do quadrante "EXPANSION" e o rótulo de regime "INFLATION".

```tsx
// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
vi.mock("@/lib/api/client", () => ({
  fetchMacroRegime: vi.fn().mockResolvedValue({
    detector: "vote2of3", state: "risk_on", vote_count: 1,
    votes: { credit: false, trend: true, nfci: false },
    as_of: "2026-06-18", days_in_state: 10, last_flip: null,
    signal: { ratio: 1, p20_5y: 0.9, distance_pct: 5, nfci: -0.2 },
    recent_flips: [], history: [],
    macro_quadrant: {
      as_of: "2026-06-18", quadrant: "EXPANSION",
      growth_state: "up", inflation_state: "up",
      growth_score: 0.07, inflation_score: 0.02, regime: "INFLATION",
      bands: [
        { asset_class: "equity", min_weight: 0.30, max_weight: 0.54 },
        { asset_class: "fixed_income", min_weight: 0.16, max_weight: 0.34 },
        { asset_class: "alternatives", min_weight: 0.13, max_weight: 0.31 },
        { asset_class: "cash", min_weight: 0.05, max_weight: 0.17 },
      ],
    },
  }),
}));
// + QueryClientProvider wrapper as the existing MacroRegimeView tests use

it("shows current quadrant and combined regime", async () => {
  // render <MacroRegimeView /> inside a QueryClientProvider
  await waitFor(() => expect(screen.getByText(/EXPANSION/i)).toBeInTheDocument());
  expect(screen.getByText(/INFLATION/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Rodar e ver falhar** — `cd frontend && pnpm test src/components/macro/MacroRegimeView.quadrant.test.tsx`.
- [ ] **Step 3: Implementar** a seção nova (quadrante + escores + regime + gráfico de bandas).
- [ ] **Step 4: Rodar e ver passar** + `pnpm run typecheck`.
- [ ] **Step 5: Commit** — `git add frontend/src/components/macro/MacroRegimeView.tsx frontend/src/components/macro/MacroRegimeView.quadrant.test.tsx && git commit -m "Show macro quadrant and regime bands on Macro page"`.

---

### Task 5: Gate verde do Componente 4

- [ ] **Step 1: Backend** `cd backend && .venv/Scripts/python -m pytest -q` → verde (ou só falhas pré-existentes conhecidas).
- [ ] **Step 2: Frontend** `cd frontend && pnpm test && pnpm run typecheck && pnpm build`.
- [ ] **Step 3: Commit** de ajustes de gate, se houver.

## Self-Review (cobertura do spec §4.4 / §5 componente 4)
- Quadrante dirigido pelos novos fatores (via `macro_factor_daily` → `/macro/regime`) → Task 1.
- Tipos regenerados + client → Task 2.
- Gráfico de bandas por classe → Task 3.
- Exibir quadrante atual + bandas resultantes em `MacroRegimeView` → Task 4.
- `multi_asset` fora das bandas (O3): só 4 classes exibidas → Global Constraints/Task 3.
- Empty-state quando `macro_factor_daily` vazia → Task 4 Produces.
- Consistência de tipos: `MacroQuadrantOut.bands` (backend) ↔ `bands` param de `buildHcMacroBandsOption` ↔ prop em `MacroRegimeView`.
```
