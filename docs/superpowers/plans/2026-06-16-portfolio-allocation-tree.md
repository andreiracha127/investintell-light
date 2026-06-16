# Portfolio Allocation tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only **Allocation** section to the portfolio page that renders holdings as a 3-level Highcharts Grid Pro tree (Asset Class → Strategy → Holding) with a top-level Cash node, reusing the builder's grid adapter unchanged.

**Architecture:** Backend enriches each `PositionOverview` with `asset_class`/`strategy_label`/`instrument_id` (resolved from the existing fund-instrument resolver + the T7 taxonomy loaders) via a new pure `resolve_position_taxonomy` helper passed into `build_overview`. The frontend maps the enriched positions through a new pure `buildAllocationTree` transform into `WeightTreeRow[]` and renders them with the **unchanged** `weightsTreeGridOptions` + `DataGrid`.

**Tech Stack:** Python 3.13 / pydantic / SQLAlchemy async (backend); TypeScript, React 19, @tanstack/react-query, vitest + @testing-library/react (jsdom), Highcharts Grid Pro 3.0.0 (frontend).

**Spec:** `docs/superpowers/specs/2026-06-16-portfolio-allocation-tree-design.md`.

---

## Convenções (LER ANTES DE CADA TASK)

- **Working dir:** `E:\investintell-light`. Frontend em `frontend/`, backend em `backend/`.
- **Frontend (pnpm):** type-check `cd frontend && pnpm run typecheck`; testes `cd frontend && pnpm vitest run <path>`.
- **Backend:** `cd backend && python -m pytest <path> -q`; lint `python -m ruff check <files>` (line-length=100).
- **Padrão de teste frontend:** primeira linha `// @vitest-environment jsdom` quando renderiza; `vi.mock("@/lib/api/client", ...)` para rede; mockar `@/components/ui/DataGrid`; `userEvent.setup()`; `afterEach(cleanup)`. jest-dom (`toBeInTheDocument`) já é global.
- **TDD:** escreva o teste falhando, rode p/ confirmar a falha, implemente, rode p/ verde, commit.
- **Trailer de commit:**
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **Pré-existente (NÃO consertar):** `pnpm run typecheck` tem 4 erros pré-existentes em `src/lib/charts/hc/rebalance.test.ts` (`status`). O critério é: **nenhum erro NOVO** nos arquivos tocados.
- **Reuso:** `weightsTreeGridOptions`, `weightLabelFormatter`, `DataGrid` e o tipo `WeightTreeRow` (de `@/lib/builder/weightsTree`) são reutilizados SEM alteração. Os loaders `load_fund_asset_class`/`load_fund_strategy_label` já existem em `app/optimizer/data.py`.

---

## File structure

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `backend/app/schemas/portfolios.py` | Modify | `PositionOverview` += `asset_class`/`strategy_label`/`instrument_id` (T1). |
| `backend/app/services/portfolio_crud.py` | Modify | `PositionTaxonomy` NamedTuple + `build_overview` aceita `taxonomy_by_ticker` (T1); `resolve_position_taxonomy` helper (T2). |
| `backend/tests/test_portfolios_overview.py` | Modify | Unit de `build_overview` taxonomy (T1); unit de `resolve_position_taxonomy` + stub de rota + assert na resposta (T2). |
| `backend/openapi.json` + `frontend/src/lib/api/api.d.ts` | Modify (gerado) | Regen com os campos novos (T3). |
| `frontend/src/lib/portfolio/allocationTree.ts` | Create | `buildAllocationTree` puro (nó Cash, fallback "Direct equity", agregação) (T4). |
| `frontend/src/lib/portfolio/allocationTree.test.ts` | Create | Unit de `buildAllocationTree` (T4). |
| `frontend/src/components/portfolio/PortfolioAllocationSection.tsx` | Create | Seção read-only que reutiliza `weightsTreeGridOptions` + `DataGrid` (T5). |
| `frontend/src/components/portfolio/PortfolioAllocationSection.test.tsx` | Create | Render smoke (mock DataGrid) (T5). |
| `frontend/src/components/portfolio/PortfolioOverviewView.tsx` | Modify | Renderiza `<PortfolioAllocationSection>` abaixo do grid de holdings (T5). |

---

## Task 1: Backend — `PositionOverview` taxonomy + `build_overview` param

**Files:**
- Modify: `backend/app/schemas/portfolios.py` (`PositionOverview`, ~line 192)
- Modify: `backend/app/services/portfolio_crud.py` (`build_overview`, ~line 510; add `PositionTaxonomy`)
- Modify: `backend/tests/test_portfolios_overview.py` (append a pure unit test)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_portfolios_overview.py` (the pure-math section near `test_build_overview_as_of_is_max_across_positions`):

```python
def test_build_overview_populates_taxonomy_from_map() -> None:
    import uuid as _uuid

    from app.services.portfolio_crud import PositionTaxonomy

    iid = _uuid.UUID(int=7)
    rows, _ = build_overview(
        [_position("VTI", 1.0, 10.0), _position("AAPL", 1.0, 10.0)],
        closes_by_ticker={"VTI": [(_LAST, 10.0)], "AAPL": [(_LAST, 10.0)]},
        names_by_ticker={},
        cash=0.0,
        taxonomy_by_ticker={
            "VTI": PositionTaxonomy("equity", "Large-Cap Blend", iid),
        },
    )
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["VTI"].asset_class == "equity"
    assert by_ticker["VTI"].strategy_label == "Large-Cap Blend"
    assert by_ticker["VTI"].instrument_id == iid
    # Ticker absent from the map → all-None taxonomy (default).
    assert by_ticker["AAPL"].asset_class is None
    assert by_ticker["AAPL"].strategy_label is None
    assert by_ticker["AAPL"].instrument_id is None


def test_build_overview_taxonomy_defaults_none_when_map_omitted() -> None:
    rows, _ = build_overview(
        [_position("AAPL", 1.0, 10.0)],
        closes_by_ticker={"AAPL": [(_LAST, 10.0)]},
        names_by_ticker={},
        cash=0.0,
    )
    assert rows[0].asset_class is None
    assert rows[0].instrument_id is None
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd backend && python -m pytest tests/test_portfolios_overview.py -k taxonomy -q`
  Expected: FAIL — `ImportError`/`TypeError`: `PositionTaxonomy` not defined and `build_overview` has no `taxonomy_by_ticker` kwarg.

- [ ] **Step 3a: Schema.** In `backend/app/schemas/portfolios.py`, in `PositionOverview` (after the `name` field, ~line 193), add:
```python
    asset_class: str | None = Field(
        default=None,
        description="Fund asset_class for the grouped allocation view; None for "
        "direct equities / non-fund tickers.",
    )
    strategy_label: str | None = Field(
        default=None,
        description="Fund strategy_label for the grouped allocation view; None "
        "for direct equities.",
    )
    instrument_id: uuid.UUID | None = Field(
        default=None,
        description="Fund instrument_id (for the dossier link); None for "
        "non-fund holdings.",
    )
```
> `schemas/portfolios.py` does NOT currently import `uuid`. Add `import uuid` right after `import datetime as dt` (line 12).

- [ ] **Step 3b: `PositionTaxonomy` + `build_overview` param.** In `backend/app/services/portfolio_crud.py`:

Three import edits (the file currently has `import datetime as dt` on line 11, `from collections.abc import Sequence` on line 12, and `from typing import Any, Protocol, cast` on line 14; it does NOT import `uuid`):

1. Add `import uuid` right after `import datetime as dt` (line 11).
2. Replace `from collections.abc import Sequence` with:
```python
from collections.abc import Mapping, Sequence
```
3. Replace `from typing import Any, Protocol, cast` with:
```python
from typing import Any, NamedTuple, Protocol, cast
```

(b) Immediately before `def build_overview(` (~line 510), add the taxonomy tuple:
```python
class PositionTaxonomy(NamedTuple):
    """Per-position fund taxonomy for the grouped allocation view."""

    asset_class: str | None
    strategy_label: str | None
    instrument_id: uuid.UUID | None
```

(c) Change the `build_overview` signature to add `taxonomy_by_ticker` as the LAST parameter (so the existing `cash`-keyword callers and tests keep working):
```python
def build_overview(
    positions: Sequence[PositionLike],
    closes_by_ticker: dict[str, list[tuple[dt.date, float]]],
    names_by_ticker: dict[str, str | None],
    cash: float,
    taxonomy_by_ticker: Mapping[str, PositionTaxonomy] | None = None,
) -> tuple[list[PositionOverview], OverviewAggregates]:
```

(d) Inside the row loop, right before `rows.append(`, resolve the taxonomy for this ticker:
```python
        tax = (taxonomy_by_ticker or {}).get(
            position.ticker, PositionTaxonomy(None, None, None)
        )
```
and add the three fields to the `PositionOverview(...)` constructor (after `as_of=as_of,`):
```python
                asset_class=tax.asset_class,
                strategy_label=tax.strategy_label,
                instrument_id=tax.instrument_id,
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd backend && python -m pytest tests/test_portfolios_overview.py -q`
  Expected: green (new taxonomy tests pass; all existing overview tests still pass — they omit `taxonomy_by_ticker` and get all-None).

- [ ] **Step 5: Commit.**
```bash
git add backend/app/schemas/portfolios.py backend/app/services/portfolio_crud.py backend/tests/test_portfolios_overview.py
git commit -m "feat(portfolio): PositionOverview carries fund taxonomy via build_overview map (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Backend — `resolve_position_taxonomy` + overview route wiring

**Files:**
- Modify: `backend/app/services/portfolio_crud.py` (add `resolve_position_taxonomy`; import the loaders)
- Modify: `backend/app/api/routes/portfolios.py` (resolve + pass into `build_overview`, ~line 290)
- Modify: `backend/tests/test_portfolios_overview.py` (unit of resolver + route stub + assert)

- [ ] **Step 1: Write the failing tests.** In `backend/tests/test_portfolios_overview.py`:

(a) Append a unit test for the resolver:
```python
async def test_resolve_position_taxonomy_funds_vs_equities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid as _uuid

    from app.optimizer import data as optimizer_data
    from app.services import portfolio_crud

    iid = _uuid.UUID(int=11)

    async def fake_instr(session, tickers):
        return {"VTI": iid}  # AAPL absent → direct equity

    async def fake_class(session, fund_ids):
        return {iid: "equity"}

    async def fake_strategy(session, fund_ids):
        return {iid: "Large-Cap Blend"}

    monkeypatch.setattr(portfolio_crud, "_fund_instrument_by_ticker", fake_instr)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)

    out = await portfolio_crud.resolve_position_taxonomy(None, ["VTI", "AAPL"])  # type: ignore[arg-type]
    assert out["VTI"] == portfolio_crud.PositionTaxonomy("equity", "Large-Cap Blend", iid)
    assert out["AAPL"] == portfolio_crud.PositionTaxonomy("equity", None, None)
```

(b) In `_install_stubs` (the route-test harness, ~line 70–114), add a default stub so the route's new resolver call does not hit `session=None`. After the existing `monkeypatch.setattr(portfolio_crud, "select_fund_names", fake_fund_names)` line add:
```python
    async def fake_taxonomy(session, tickers):
        return {t: portfolio_crud.PositionTaxonomy(None, None, None) for t in tickers}

    monkeypatch.setattr(portfolio_crud, "resolve_position_taxonomy", fake_taxonomy)
```

(c) Append a route test that overrides the taxonomy stub and asserts the response carries it:
```python
async def test_overview_response_includes_position_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid as _uuid

    _install_stubs(
        monkeypatch,
        _portfolio([_position("VTI", 1.0, 10.0)], cash=0.0),
        closes={"VTI": [(_LAST, 10.0)]},
    )
    iid = _uuid.UUID(int=11)

    async def fake_taxonomy(session, tickers):
        return {"VTI": portfolio_crud.PositionTaxonomy("equity", "Large-Cap Blend", iid)}

    monkeypatch.setattr(portfolio_crud, "resolve_position_taxonomy", fake_taxonomy)
    async with _client() as ac:
        resp = await ac.get("/portfolios/1/overview")
    assert resp.status_code == 200, resp.text
    pos = resp.json()["positions"][0]
    assert pos["asset_class"] == "equity"
    assert pos["strategy_label"] == "Large-Cap Blend"
    assert pos["instrument_id"] == str(iid)
```
> Confirm `portfolio_crud` and `_position`/`_portfolio`/`_LAST`/`_client`/`_install_stubs` are already imported/defined in this test module (they are — used by the existing route tests). Add `from app.services import portfolio_crud` at the top if not already imported.

- [ ] **Step 2: Run, expect FAIL.** Run: `cd backend && python -m pytest tests/test_portfolios_overview.py -k "taxonomy" -q`
  Expected: FAIL — `AttributeError`: `portfolio_crud` has no `resolve_position_taxonomy`.

- [ ] **Step 3a: Resolver.** In `backend/app/services/portfolio_crud.py`, add the import near the other app imports (top of file):
```python
from app.optimizer import data as optimizer_data
```
Then add the resolver immediately after `_fund_instrument_by_ticker` (ends ~line 370):
```python
async def resolve_position_taxonomy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, PositionTaxonomy]:
    """ticker -> PositionTaxonomy for the grouped allocation view.

    Fund tickers resolve to their instrument_id (via _fund_instrument_by_ticker)
    and carry the fund asset_class / strategy_label. Any ticker that does not
    resolve to a fund instrument is treated as a directly-held equity:
    ('equity', None, None).
    """
    if not tickers:
        return {}
    instrument_by_ticker = await _fund_instrument_by_ticker(session, tickers)
    instrument_ids = list({iid for iid in instrument_by_ticker.values()})
    asset_class_of = await optimizer_data.load_fund_asset_class(session, instrument_ids)
    strategy_of = await optimizer_data.load_fund_strategy_label(session, instrument_ids)
    out: dict[str, PositionTaxonomy] = {}
    for ticker in tickers:
        iid = instrument_by_ticker.get(ticker)
        if iid is None:
            out[ticker] = PositionTaxonomy("equity", None, None)
        else:
            out[ticker] = PositionTaxonomy(
                asset_class_of.get(iid), strategy_of.get(iid), iid
            )
    return out
```
> Keep the loader calls as `optimizer_data.load_fund_*` (module-attribute) so the test monkeypatch applies.

- [ ] **Step 3b: Route wiring.** In `backend/app/api/routes/portfolios.py`, replace the `build_overview` call (~line 289–292):
```python
    try:
        rows, aggregates = portfolio_crud.build_overview(
            portfolio.positions, closes, names, cash=portfolio.cash
        )
```
with:
```python
    taxonomy = await portfolio_crud.resolve_position_taxonomy(session, tickers)
    try:
        rows, aggregates = portfolio_crud.build_overview(
            portfolio.positions,
            closes,
            names,
            cash=portfolio.cash,
            taxonomy_by_ticker=taxonomy,
        )
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd backend && python -m pytest tests/test_portfolios_overview.py -q`
  Expected: green (resolver unit + route taxonomy assert pass; existing route tests stay green via the `_install_stubs` default).

- [ ] **Step 5: Lint + commit.**
```bash
cd backend && python -m ruff check app/services/portfolio_crud.py app/api/routes/portfolios.py app/schemas/portfolios.py
git add backend/app/services/portfolio_crud.py backend/app/api/routes/portfolios.py backend/tests/test_portfolios_overview.py
git commit -m "feat(portfolio): resolve per-position fund taxonomy in overview route (T2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Regenerate the API contract

**Files:** Modify (generated): `backend/openapi.json`, `frontend/src/lib/api/api.d.ts`

- [ ] **Step 1: Regenerate.** Run:
```
cd backend && python scripts/export_openapi.py
cd frontend && pnpm dlx openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts
```

- [ ] **Step 2: Confirm.** Run: `cd frontend && grep -A20 "PositionOverview: {" src/lib/api/api.d.ts | grep -E "asset_class|strategy_label|instrument_id"`
  Expected: `asset_class?: string | null;`, `strategy_label?: string | null;`, and `instrument_id?: string | null;` all present.

- [ ] **Step 3: Commit.**
```bash
git add backend/openapi.json frontend/src/lib/api/api.d.ts
git commit -m "chore(contract): regen openapi + api.d.ts with PositionOverview taxonomy (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — `buildAllocationTree` (pure transform)

**Files:**
- Create: `frontend/src/lib/portfolio/allocationTree.ts`
- Create: `frontend/src/lib/portfolio/allocationTree.test.ts`

- [ ] **Step 1: Write the failing test.** Create `frontend/src/lib/portfolio/allocationTree.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildAllocationTree, type AllocationInput } from "./allocationTree";

function h(over: Partial<AllocationInput> = {}): AllocationInput {
  return {
    ticker: "VTI",
    name: "Vanguard Total Market",
    marketValue: 100,
    assetClass: "equity",
    strategyLabel: "Large-Cap Blend",
    instrumentId: "iid-1",
    ...over,
  };
}

describe("buildAllocationTree", () => {
  it("returns [] when totalValue is 0", () => {
    expect(buildAllocationTree([h()], 0, 0)).toEqual([]);
  });

  it("prepends a top-level Cash node ordered by weight, no children", () => {
    // holdings 60, cash 40, total 100 → equity 0.6 root precedes cash 0.4 root.
    const rows = buildAllocationTree(
      [h({ marketValue: 60 })],
      100,
      40,
    );
    const roots = rows.filter((r) => r.parentId === null);
    expect(roots.map((r) => r.label)).toEqual(["Equity", "Cash"]);
    const cash = rows.find((r) => r.id === "ac:__cash__");
    expect(cash?.weight).toBeCloseTo(0.4, 9);
    expect(cash?.instrumentId).toBeNull();
    // Cash has no children.
    expect(rows.some((r) => r.parentId === "ac:__cash__")).toBe(false);
  });

  it("funds keep instrumentId + their strategy; aggregates parent weights", () => {
    const rows = buildAllocationTree(
      [
        h({ ticker: "A", marketValue: 20, strategyLabel: "Growth", instrumentId: "a" }),
        h({ ticker: "B", marketValue: 30, strategyLabel: "Growth", instrumentId: "b" }),
      ],
      100,
      50,
    );
    const byId = new Map(rows.map((r) => [r.id, r]));
    expect(byId.get("ac:equity")?.weight).toBeCloseTo(0.5, 9);
    expect(byId.get("st:equity/Growth")?.weight).toBeCloseTo(0.5, 9);
    const leafA = rows.find((r) => r.label === "A");
    expect(leafA?.instrumentId).toBe("a");
    expect(leafA?.parentId).toBe("st:equity/Growth");
  });

  it("direct equities (no instrumentId) fall under 'Direct equity' with null leaf id", () => {
    const rows = buildAllocationTree(
      [h({ ticker: "AAPL", marketValue: 100, strategyLabel: null, instrumentId: null })],
      100,
      0,
    );
    const strat = rows.find((r) => r.id.startsWith("st:"));
    expect(strat?.label).toBe("Direct equity");
    const leaf = rows.find((r) => r.label === "AAPL");
    expect(leaf?.instrumentId).toBeNull();
  });

  it("drops sub-floor weights", () => {
    const rows = buildAllocationTree(
      [
        h({ ticker: "A", marketValue: 100, instrumentId: "a" }),
        h({ ticker: "Z", marketValue: 0, instrumentId: "z" }),
      ],
      100,
      0,
    );
    expect(rows.some((r) => r.label === "Z")).toBe(false);
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/lib/portfolio/allocationTree.test.ts`
  Expected: FAIL — module `./allocationTree` does not exist.

- [ ] **Step 3: Implement.** Create `frontend/src/lib/portfolio/allocationTree.ts`:

```ts
/**
 * Pure transform: portfolio holdings → ordered tree rows for the Grid Pro
 * parent-id tree (Asset Class → Strategy → Holding) with a top-level Cash node.
 * Reuses the builder's `WeightTreeRow` output contract so the grid adapter
 * (`weightsTreeGridOptions`) renders it unchanged. Weights are fractions of the
 * total portfolio value (incl. cash); zero-weight holdings are dropped; parent
 * rows carry the aggregated weight of their children. Fund leaves carry the
 * `instrumentId` (for the dossier link); direct equities do not.
 */
import type { WeightTreeRow } from "@/lib/builder/weightsTree";

/** One portfolio holding, decoupled from the generated API type. */
export interface AllocationInput {
  ticker: string | null;
  name: string | null;
  marketValue: number;
  assetClass: string | null;
  strategyLabel: string | null;
  instrumentId: string | null;
}

const WEIGHT_FLOOR = 1e-6;
const CASH_ID = "ac:__cash__";

const ASSET_CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
};

interface Strat {
  label: string;
  weight: number;
  funds: { input: AllocationInput; weight: number }[];
}
interface Root {
  id: string;
  label: string;
  weight: number;
  /** Asset-class groups have strategies; the cash node has none. */
  strategies: Map<string, Strat> | null;
}

export function buildAllocationTree(
  holdings: AllocationInput[],
  totalValue: number,
  cashValue: number,
): WeightTreeRow[] {
  if (totalValue <= 0) return [];

  const groups = new Map<string, Root & { code: string }>();
  for (const hld of holdings) {
    const weight = hld.marketValue / totalValue;
    if (weight <= WEIGHT_FLOOR) continue;
    const code = hld.assetClass ?? "__other__";
    const acLabel = hld.assetClass
      ? (ASSET_CLASS_LABEL[hld.assetClass] ?? hld.assetClass)
      : "Other";
    // Funds without a strategy → "Unclassified"; non-fund holdings → "Direct equity".
    const stratLabel =
      hld.strategyLabel ?? (hld.instrumentId ? "Unclassified" : "Direct equity");
    let g = groups.get(code);
    if (!g) {
      g = { id: `ac:${code}`, code, label: acLabel, weight: 0, strategies: new Map() };
      groups.set(code, g);
    }
    g.weight += weight;
    const strategies = g.strategies as Map<string, Strat>;
    let s = strategies.get(stratLabel);
    if (!s) {
      s = { label: stratLabel, weight: 0, funds: [] };
      strategies.set(stratLabel, s);
    }
    s.weight += weight;
    s.funds.push({ input: hld, weight });
  }

  const roots: Root[] = [...groups.values()];
  if (cashValue > WEIGHT_FLOOR * totalValue) {
    roots.push({
      id: CASH_ID,
      label: "Cash",
      weight: cashValue / totalValue,
      strategies: null,
    });
  }

  const byWeightDesc = <T extends { weight: number }>(a: T, b: T) => b.weight - a.weight;

  const rows: WeightTreeRow[] = [];
  let leafSeq = 0;
  for (const root of roots.sort(byWeightDesc)) {
    rows.push({
      id: root.id,
      parentId: null,
      label: root.label,
      weight: root.weight,
      instrumentId: null,
    });
    if (root.strategies === null) continue; // cash node: no children
    const code = root.id.slice("ac:".length);
    for (const s of [...root.strategies.values()].sort(byWeightDesc)) {
      const stId = `st:${code}/${s.label}`;
      rows.push({
        id: stId,
        parentId: root.id,
        label: s.label,
        weight: s.weight,
        instrumentId: null,
      });
      for (const f of [...s.funds].sort(byWeightDesc)) {
        rows.push({
          id: `leaf:${f.input.instrumentId ?? f.input.ticker ?? `seq${leafSeq}`}`,
          parentId: stId,
          label: f.input.ticker ?? f.input.name ?? "—",
          weight: f.weight,
          instrumentId: f.input.instrumentId,
        });
        leafSeq += 1;
      }
    }
  }
  return rows;
}
```

- [ ] **Step 4: Run, expect PASS.** Run: `cd frontend && pnpm vitest run src/lib/portfolio/allocationTree.test.ts`
  Expected: 5 passed.

- [ ] **Step 5: Commit.**
```bash
git add frontend/src/lib/portfolio/allocationTree.ts frontend/src/lib/portfolio/allocationTree.test.ts
git commit -m "feat(portfolio): pure holdings→allocation tree transform (cash node, equity fallback) (T4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend — `PortfolioAllocationSection` + view wiring

**Files:**
- Create: `frontend/src/components/portfolio/PortfolioAllocationSection.tsx`
- Create: `frontend/src/components/portfolio/PortfolioAllocationSection.test.tsx`
- Modify: `frontend/src/components/portfolio/PortfolioOverviewView.tsx`

- [ ] **Step 1: Write the failing test.** Create `frontend/src/components/portfolio/PortfolioAllocationSection.test.tsx`:

```tsx
// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PortfolioAllocationSection } from "./PortfolioAllocationSection";
import type { PortfolioOverview } from "@/lib/api/client";

vi.mock("@/components/ui/DataGrid", () => ({
  DataGrid: ({ options }: { options: unknown }) => (
    <div data-testid="datagrid" data-rows={JSON.stringify(options).length} />
  ),
}));

afterEach(cleanup);

const overview = {
  id: 1,
  name: "P",
  positions: [
    {
      ticker: "VTI",
      name: "Vanguard",
      market_value: 60,
      asset_class: "equity",
      strategy_label: "Large-Cap Blend",
      instrument_id: "iid-1",
    },
  ],
  aggregates: { total_value: 100, total_market_value: 60, cash: 40 },
} as unknown as PortfolioOverview;

describe("PortfolioAllocationSection", () => {
  it("renders the allocation grid for a portfolio with holdings", () => {
    render(<PortfolioAllocationSection overview={overview} />);
    expect(screen.getByTestId("datagrid")).toBeInTheDocument();
    expect(screen.getByText(/Allocation/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no holdings and no cash", () => {
    const empty = {
      ...overview,
      positions: [],
      aggregates: { total_value: 0, total_market_value: 0, cash: 0 },
    } as unknown as PortfolioOverview;
    const { container } = render(<PortfolioAllocationSection overview={empty} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.** Run: `cd frontend && pnpm vitest run src/components/portfolio/PortfolioAllocationSection.test.tsx`
  Expected: FAIL — module `./PortfolioAllocationSection` does not exist.

- [ ] **Step 3: Implement the component.** Create `frontend/src/components/portfolio/PortfolioAllocationSection.tsx`:

```tsx
"use client";

import { DataGrid } from "@/components/ui/DataGrid";
import { Card } from "@/components/ui/panels";
import type { PortfolioOverview } from "@/lib/api/client";
import { buildAllocationTree, type AllocationInput } from "@/lib/portfolio/allocationTree";
import { weightsTreeGridOptions } from "@/lib/grid/weightsTreeGridOptions";

/**
 * Read-only allocation breakdown: a 3-level Asset Class → Strategy → Holding
 * tree (with a top-level Cash node) of the portfolio's market-value weights.
 * Reuses the builder's tree grid adapter unchanged. The editable holdings grid
 * (PositionsTable) is separate and unaffected.
 */
export function PortfolioAllocationSection({
  overview,
}: {
  overview: PortfolioOverview;
}) {
  const { positions, aggregates } = overview;
  const totalValue = aggregates.total_value;
  const cashValue = aggregates.cash;
  if (totalValue <= 0) return null;

  const rows = buildAllocationTree(
    positions.map<AllocationInput>((p) => ({
      ticker: p.ticker ?? null,
      name: p.name ?? null,
      marketValue: p.market_value,
      assetClass: p.asset_class ?? null,
      strategyLabel: p.strategy_label ?? null,
      instrumentId: p.instrument_id ?? null,
    })),
    totalValue,
    cashValue,
  );
  if (rows.length === 0) return null;

  return (
    <Card title="Allocation" subtitle="asset class → strategy → holding">
      <DataGrid
        options={weightsTreeGridOptions(rows)}
        className="h-[420px] w-full"
        emptyMessage="No holdings to allocate."
      />
    </Card>
  );
}
```
> Confirm `Card` is exported from `@/components/ui/panels` (PortfolioOverviewView imports it from there). If the `Card` prop names differ (`title`/`subtitle`), match the existing usage in `PortfolioOverviewView.tsx`.

- [ ] **Step 4: Run the component test, expect PASS.** Run: `cd frontend && pnpm vitest run src/components/portfolio/PortfolioAllocationSection.test.tsx`
  Expected: 2 passed.

- [ ] **Step 5: Wire into the view.** In `frontend/src/components/portfolio/PortfolioOverviewView.tsx`:

(a) Add the import near the other portfolio-component imports (~line 50):
```tsx
import { PortfolioAllocationSection } from "@/components/portfolio/PortfolioAllocationSection";
```

(b) Render it below the holdings table. Replace:
```tsx
      <PositionsTable overview={overview} portfolioId={portfolioId} />
    </>
  );
}
```
with:
```tsx
      <PositionsTable overview={overview} portfolioId={portfolioId} />
      <PortfolioAllocationSection overview={overview} />
    </>
  );
}
```

- [ ] **Step 6: Type-check (no new errors in touched files).** Run: `cd frontend && pnpm run typecheck 2>&1 | grep -E "allocationTree|PortfolioAllocationSection|PortfolioOverviewView"`
  Expected: no output (no errors in any touched file). Fix any NEW error.

- [ ] **Step 7: Commit.**
```bash
git add frontend/src/components/portfolio/PortfolioAllocationSection.tsx frontend/src/components/portfolio/PortfolioAllocationSection.test.tsx frontend/src/components/portfolio/PortfolioOverviewView.tsx
git commit -m "feat(portfolio): read-only Allocation tree section on the portfolio page (T5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Final gate — type-check + tests + lint

**Files:** (verificação)

- [ ] **Step 1: Frontend type-check.** Run: `cd frontend && pnpm run typecheck`
  Expected: SOMENTE os 4 erros pré-existentes em `src/lib/charts/hc/rebalance.test.ts` (`status`). Nenhum novo nos arquivos tocados.

- [ ] **Step 2: Frontend tests.** Run: `cd frontend && pnpm vitest run src/lib/portfolio src/components/portfolio/PortfolioAllocationSection.test.tsx src/lib/grid/weightsTreeGridOptions.test.ts`
  Expected: todas as suítes verdes (`allocationTree`, `PortfolioAllocationSection`, e o adapter reutilizado).

- [ ] **Step 3: Backend tests + lint.** Run:
  ```
  cd backend && python -m pytest tests/test_portfolios_overview.py -q
  cd backend && python -m ruff check app/services/portfolio_crud.py app/api/routes/portfolios.py app/schemas/portfolios.py
  ```
  Expected: verde; ruff limpo.

- [ ] **Step 4: Visual check (manual).** Rode o app (`cd frontend && pnpm dev` + backend) e abra `/portfolio`: selecione uma carteira com fundos + ações + caixa. Confirme: (a) abaixo do grid editável de holdings surge a seção "Allocation" como tree de 3 níveis (Asset Class → Strategy → Holding), expandida; (b) um nó "Cash" no topo com o peso da caixa; (c) pesos agregados nas linhas-pai somando 100%; (d) ações sob "Direct equity" sem link; fundos com ticker linkando para `/funds/<id>`. O grid editável de holdings continua intocado.

- [ ] **Step 5: Commit (se o gate exigiu ajustes).**
```bash
git add -A
git commit -m "test(portfolio): allocation tree gate (T6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notas de escopo

- **Reuso máximo:** `weightsTreeGridOptions`, `weightLabelFormatter`, `DataGrid` e `WeightTreeRow` são reutilizados sem alteração. `buildAllocationTree` duplica deliberadamente a lógica de agrupamento de `buildWeightsTree` (~50 linhas) para manter o builder intocado e isolar o tratamento de caixa/ação; extrair um core compartilhado fica como follow-up se a duplicação incomodar.
- **Grid editável intocado:** a tabela de holdings (`PositionsTable`/`positionsToGridOptions`, com edição de cost/shares/remove e updates de "last") não muda.
- **Equity asset_class:** tickers não-fundo assumem `asset_class="equity"` (sem lookup de classe por ação no escopo) — simplificação registrada no spec.
- **Caixa:** lida via `aggregates.cash` (já exposto no frontend), peso sobre `total_value`; a tree soma 100%.
