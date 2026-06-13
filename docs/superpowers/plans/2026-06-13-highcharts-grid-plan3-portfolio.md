# Highcharts Grid Pro — Portfolio positions + cell editing (Plano 3/5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Migrar a tabela de posições do `PortfolioOverviewView` para o `DataGrid`, com **cell editing Pro** em shares/cost (persistindo via `putPosition`), replicando as colunas decoradas (ticker link + nome, último/variação, custo com badge EXEC/REF + comissão, P&L, valor de mercado), os **agregados nos headers** de P&L e Mkt Value, a remoção por linha e a linha de **adicionar posição** (anexada ao grid, ver nota). Reusa a fundação (DataGrid, tema, tipos).

**Architecture:** Grid renderiza; TanStack Query é a fonte e dona das mutations. Um adapter PURO `positionsToGridOptions(overview, callbacks)` constrói as colunas (com formatters HTML, `editMode` nas editáveis, agregados nos headers via `header.format` calculado, coluna de ação ×) e fia os eventos: `cells.events.afterEdit` despacha para `onEditShares`/`onEditCost`; o clique na coluna de ação chama `onRemove`. As callbacks (validação + mutations) vivem no componente. O formulário de adição é renderizado contíguo ao grid (o grid não hospeda input add-row nativamente).

**Tech Stack:** Next 15/React 19, TS, `@highcharts/grid-pro@3.0.0`, TanStack Query v5, Vitest (só o adapter puro é unit-testável; a edição interativa é validada por build + browser).

**Branch:** `feat/highcharts-grid-rollout`.

---

## Contexto (fatos verificados — lidos do código)
- `PortfolioOverviewView.tsx`: `OverviewSection` mostra `KpiStrip` (já exibe Total Value/P&L/Mkt/Cash/Positions — os agregados JÁ existem fora da tabela), `AllocationPanel` (EChart) e `PositionsTable`. **Mantemos KpiStrip e AllocationPanel intactos.**
- `PositionsTable` tem: `addMutation`/`editMutation`/`removeMutation` (todas sobre `putPosition`/`deletePosition` com `invalidate()`), o `<table>` com `AddPositionRow` + `PositionRow[]`, e um footer (EOD/cash/total). Aggregates P&L e Mkt Value vão nos `<th>`.
- `OverviewPosition`: `ticker, name(string|null), last_close, change(|null), change_pct(|null), acq_price(number|null), quantity(number), basis('executed'|outro), commission(number|null), trade_date(string|null), pnl(|null), pnl_pct(|null), market_value(number)`.
- `PortfolioOverview`: `{ name, positions: OverviewPosition[], aggregates: { total_value, total_pnl(|null), total_pnl_pct(|null), total_market_value, cash, as_of(string|null) } }`.
- `PositionBody = { quantity: number; acq_price: number | null }`. `putPosition(portfolioId, ticker, body)`, `deletePosition(portfolioId, ticker)` de `@/lib/api/client`.
- Helpers `@/lib/format`: `formatCurrency(v, opts?: {signed?:boolean})`, `formatPercent(v, decimals?, opts?)`, `formatNumber(v, decimals?)`, `formatDate(v)`. `valueTone(v)` de `@/components/ui/panels`. `formatShares` é local (8→"8", 8.5→"8.50"); replicar no adapter.
- Edição (API verificada): `ColumnCellOptions.editMode = { enabled?: boolean; renderer? }` (com `dataType:'number'`, o input default é numérico); `CellEvents.afterEdit (this: TableCell)` dispara após editar — `this.value` (novo valor parseado), `this.column?.id`, `this.row.getCell(id)?.value`. `CellEvents.click` para a coluna de ação. `Row.getCell(columnId)` para acesso cross-coluna. Coluna oculta = `enabled:false`.

## File Structure
- **Create** `frontend/src/lib/grid/positionsGridOptions.ts` — adapter PURO (colunas + formatters + editMode + afterEdit dispatch + coluna de ação + agregados nos headers). + tests.
- **Create** `frontend/src/lib/grid/positionsGridOptions.test.ts`.
- **Modify** `frontend/src/lib/grid/grid-theme.css` — classes para custo (badge EXEC/REF, comissão), sub-linha de variação/pnl, ação ×.
- **Modify** `frontend/src/components/portfolio/PortfolioOverviewView.tsx` — `PositionsTable` renderiza via `DataGrid`; wire das callbacks às mutations; `AddPositionRow` vira form contíguo (mantido); footer mantido; remover `PositionRow`, `EditableValue` (se não usado em outro lugar — é usado também no `PortfolioManageBar` p/ cash; manter `EditableValue`, remover só `PositionRow`), `TH_BASE`/`TH_CLASS`.

> **Nota de fidelidade (add-row):** o grid não hospeda uma linha de input editável para "adicionar". O `AddPositionRow` é mantido como um form **contíguo acima do grid** (mesmo `<section>`/painel, separador 1px), preservando a UX. Documentado.
> **Validação da edição:** em `afterEdit`, a callback valida (shares>0; cost vazio→null ou >0). Em valor inválido, NÃO persiste e chama `queryClient.invalidateQueries(["overview", id])` para re-render a partir do estado do servidor (reverte a célula). Em válido+mudado, dispara a mutation (que invalida no sucesso).

---

## Task 1: Classes de célula (CSS)

**Files:** Modify `frontend/src/lib/grid/grid-theme.css`

- [ ] **Step 1:** Append ao final EXATAMENTE:

```css

/* Portfolio positions cell renderers. */
.hcg-theme-graphite .ix-grid-sub { display: block; font-size: 11px; }
.hcg-theme-graphite .ix-grid-name { display: block; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-basis { display: inline-block; border: 1px solid var(--color-border-strong); padding: 1px 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.05em; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-basis-exec { border-color: var(--color-accent); color: var(--color-accent); }
.hcg-theme-graphite .ix-grid-comm { display: block; font-size: 10px; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-remove { cursor: pointer; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-remove:hover { color: var(--color-loss); }
.hcg-theme-graphite .ix-grid-editable { text-decoration: underline dotted var(--color-text-muted); text-underline-offset: 3px; }
```

- [ ] **Step 2:** Commit `feat(grid): cell classes for the portfolio positions grid` (com Co-Authored-By).

---

## Task 2: Adapter `positionsToGridOptions` (TDD nas partes puras)

**Files:** Create `frontend/src/lib/grid/positionsGridOptions.ts` + `.test.ts`

- [ ] **Step 1 — Test (failing)** `frontend/src/lib/grid/positionsGridOptions.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import type { PortfolioOverview } from "@/lib/api/client";
import {
  formatShares,
  positionsGridColumns,
  positionsGridData,
  positionsToGridOptions,
} from "./positionsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

const OVERVIEW = {
  name: "Main",
  positions: [
    {
      ticker: "AAA", name: "Alpha Inc", last_close: 10, change: 0.5, change_pct: 0.05,
      acq_price: 8, quantity: 100, basis: "executed", commission: 1.5, trade_date: "2026-01-02",
      pnl: 200, pnl_pct: 0.25, market_value: 1000,
    },
    {
      ticker: "BBB", name: null, last_close: 20, change: -1, change_pct: -0.05,
      acq_price: null, quantity: 8.5, basis: "reference", commission: null, trade_date: null,
      pnl: null, pnl_pct: null, market_value: 170,
    },
  ],
  aggregates: { total_value: 1170, total_pnl: 200, total_pnl_pct: 0.2, total_market_value: 1170, cash: 0, as_of: "2026-06-12" },
} as unknown as PortfolioOverview;

type CellLike = {
  value: unknown;
  column?: { id: string };
  row: { getCell: (id: string) => { value: unknown } | undefined };
};
const mkCell = (value: unknown, rowValues: Record<string, unknown> = {}, columnId?: string): CellLike => ({
  value,
  column: columnId ? { id: columnId } : undefined,
  row: { getCell: (id) => (id in rowValues ? { value: rowValues[id] } : undefined) },
});
const callFmt = (fn: unknown, cell: CellLike) => (fn as (this: CellLike) => string).call(cell);

describe("formatShares", () => {
  it("shows integers without decimals and fractions with two", () => {
    expect(formatShares(8)).toBe("8");
    expect(formatShares(8.5)).toBe("8.50");
  });
});

describe("positionsGridColumns", () => {
  it("includes editable shares & cost columns and a clickable action column", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const shares = cols.find((c) => c.id === "shares");
    const cost = cols.find((c) => c.id === "cost");
    const action = cols.find((c) => c.id === "__remove");
    expect(shares?.cells?.editMode?.enabled).toBe(true);
    expect(cost?.cells?.editMode?.enabled).toBe(true);
    expect(action?.cells?.events?.click).toBeTypeOf("function");
  });

  it("bakes aggregates into the P&L and Mkt Value headers", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    expect(cols.find((c) => c.id === "pnl")?.header?.format).toContain("+$200");
    expect(cols.find((c) => c.id === "mktvalue")?.header?.format).toContain("$1,170");
  });

  it("ticker formatter links to the stock and shows the name sub-line", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    const out = callFmt(fmt, mkCell("AAA", { name: "Alpha Inc" }));
    expect(out).toContain('href="/stocks/AAA"');
    expect(out).toContain("AAA");
    expect(out).toContain("Alpha Inc");
  });

  it("cost formatter shows EXEC badge + price + commission; REF when not executed", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const fmt = cols.find((c) => c.id === "cost")!.cells!.formatter;
    const exec = callFmt(fmt, mkCell(8, { basis: "executed", commission: 1.5 }));
    expect(exec).toContain("EXEC");
    expect(exec).toContain("ix-grid-basis-exec");
    const ref = callFmt(fmt, mkCell(null, { basis: "reference", commission: null }));
    expect(ref).toContain("REF");
    expect(ref).toContain("—");
  });
});

describe("positionsGridData", () => {
  it("pivots positions incl. hidden columns, null-safe", () => {
    const data = positionsGridData(OVERVIEW.positions);
    expect(data.columns.ticker).toEqual(["AAA", "BBB"]);
    expect(data.columns.shares).toEqual([100, 8.5]);
    expect(data.columns.cost).toEqual([8, null]);
    expect(data.columns.basis).toEqual(["executed", "reference"]);
    expect(data.columns.name).toEqual(["Alpha Inc", null]);
  });
});

describe("positionsToGridOptions", () => {
  it("sets theme and dispatches afterEdit to the right callback", () => {
    const onEditShares = vi.fn();
    const onEditCost = vi.fn();
    const onRemove = vi.fn();
    const opts = positionsToGridOptions(OVERVIEW, { onEditShares, onEditCost, onRemove });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    const afterEdit = opts.columnDefaults?.cells?.events?.afterEdit as unknown as (this: CellLike) => void;
    afterEdit.call(mkCell(120, { ticker: "AAA" }, "shares"));
    expect(onEditShares).toHaveBeenCalledWith("AAA", 120);
    afterEdit.call(mkCell(9, { ticker: "AAA" }, "cost"));
    expect(onEditCost).toHaveBeenCalledWith("AAA", 9);
  });
});
```

- [ ] **Step 2 — Run, confirm FAIL.**

- [ ] **Step 3 — Implement** `frontend/src/lib/grid/positionsGridOptions.ts`:

```ts
/**
 * Pure adapter: PortfolioOverview -> Highcharts Grid Pro Options for the
 * positions table. Editable shares/cost (Pro cell editing) with bespoke
 * read-only renderers (ticker link + name, change/pnl sub-lines, EXEC/REF
 * basis badge + commission), aggregates baked into the P&L / Mkt Value
 * headers, and a × action column. Pure (no React/DOM); the edit/remove
 * callbacks are injected by the component.
 */
import type { Options, TableCell } from "@highcharts/grid-pro";

import type { PortfolioOverview } from "@/lib/api/client";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type Aggregates = PortfolioOverview["aggregates"];

export interface PositionsCallbacks {
  onEditShares: (ticker: string, value: number) => void;
  onEditCost: (ticker: string, value: number | null) => void;
  onRemove: (ticker: string) => void;
}

export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Share count without fake precision: 8 -> "8", 8.5 -> "8.50". */
export function formatShares(quantity: number): string {
  return formatNumber(quantity, Number.isInteger(quantity) ? 0 : 2);
}

const toneClass = (n: number | null): string =>
  n === null ? "" : n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

/* ── read-only formatters ─────────────────────────────────────────── */
function tickerFormatter(this: GridCell): string {
  const t = escapeHtml(this.value ?? "—");
  const name = this.row.getCell("name")?.value;
  const sub = name ? `<span class="ix-grid-name">${escapeHtml(name)}</span>` : "";
  return `<a class="ix-grid-link" href="/stocks/${encodeURIComponent(String(this.value ?? ""))}">${t}</a>${sub}`;
}

function lastFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

function changeFormatter(this: GridCell): string {
  const change = num(this.value);
  const pct = num(this.row.getCell("change_pct")?.value);
  if (change === null || pct === null) return "—";
  const cls = toneClass(change);
  return `<span class="${cls}">${escapeHtml(formatCurrency(change, { signed: true }))}<span class="ix-grid-sub">${escapeHtml(formatPercent(pct, 2, { signed: true }))}</span></span>`;
}

function costFormatter(this: GridCell): string {
  const price = num(this.value);
  const basis = String(this.row.getCell("basis")?.value ?? "");
  const commission = num(this.row.getCell("commission")?.value);
  const exec = basis === "executed";
  const badge = `<span class="ix-grid-basis ${exec ? "ix-grid-basis-exec" : ""}">${exec ? "EXEC" : "REF"}</span>`;
  const value = `<span class="ix-grid-editable">${price === null ? "—" : escapeHtml(formatCurrency(price))}</span>`;
  const comm = commission === null ? "" : `<span class="ix-grid-comm">incl. comm. ${escapeHtml(formatCurrency(commission))}</span>`;
  return `${badge} ${value}${comm}`;
}

function sharesFormatter(this: GridCell): string {
  const q = num(this.value);
  return q === null ? "—" : `<span class="ix-grid-editable">${escapeHtml(formatShares(q))}</span>`;
}

function pnlFormatter(this: GridCell): string {
  const pnl = num(this.value);
  const pct = num(this.row.getCell("pnl_pct")?.value);
  if (pnl === null || pct === null) return "—";
  const cls = toneClass(pnl);
  return `<span class="${cls}">${escapeHtml(formatCurrency(pnl, { signed: true }))}<span class="ix-grid-sub">${escapeHtml(formatPercent(pct, 2, { signed: true }))}</span></span>`;
}

function mktValueFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

/* ── column + data builders ───────────────────────────────────────── */
const PNL_AGG = (a: Aggregates): string => {
  if (a.total_pnl === null) return "P&L";
  const pct = a.total_pnl_pct !== null ? ` (${formatPercent(a.total_pnl_pct, 2, { signed: true })})` : "";
  return `P&L · ${formatCurrency(a.total_pnl, { signed: true })}${pct}`;
};

const ALL_KEYS = [
  "ticker", "name", "last", "change", "change_pct", "cost", "basis", "commission",
  "shares", "pnl", "pnl_pct", "mktvalue",
] as const;

export function positionsGridColumns(aggregates: Aggregates, callbacks?: PositionsCallbacks): GridColumns {
  const cols: GridColumns = [
    { id: "ticker", header: { format: "Ticker" }, className: "ix-grid-cell-text", cells: { formatter: tickerFormatter } },
    { id: "last", header: { format: "Last" }, className: "ix-grid-cell-num", cells: { formatter: lastFormatter } },
    { id: "change", header: { format: "Change" }, className: "ix-grid-cell-num", cells: { formatter: changeFormatter } },
    { id: "cost", header: { format: "Cost" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: costFormatter, editMode: { enabled: true } } },
    { id: "shares", header: { format: "Shares" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: sharesFormatter, editMode: { enabled: true } } },
    { id: "pnl", header: { format: PNL_AGG(aggregates) }, className: "ix-grid-cell-num", cells: { formatter: pnlFormatter } },
    { id: "mktvalue", header: { format: `Mkt Value · ${formatCurrency(aggregates.total_market_value)}` }, className: "ix-grid-cell-num", cells: { formatter: mktValueFormatter } },
    {
      id: "__remove",
      header: { format: "" },
      className: "ix-grid-cell-num",
      cells: {
        formatter() { return `<span class="ix-grid-remove" title="Remove" aria-label="Remove position">×</span>`; },
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker != null && callbacks) callbacks.onRemove(String(ticker));
          },
        },
      },
    },
    // hidden data-only columns used by formatters via row.getCell
    { id: "name", enabled: false },
    { id: "change_pct", enabled: false },
    { id: "basis", enabled: false },
    { id: "commission", enabled: false },
    { id: "pnl_pct", enabled: false },
  ];
  return cols;
}

export function positionsGridData(positions: PortfolioOverview["positions"]): NonNullable<Options["data"]> {
  const map: Record<string, string> = {
    ticker: "ticker", name: "name", last: "last_close", change: "change", change_pct: "change_pct",
    cost: "acq_price", basis: "basis", commission: "commission", shares: "quantity",
    pnl: "pnl", pnl_pct: "pnl_pct", mktvalue: "market_value",
  };
  const columns: Record<string, Array<string | number | boolean | null>> = {};
  for (const [colId, field] of Object.entries(map)) {
    columns[colId] = positions.map((p) => {
      const v = (p as Record<string, unknown>)[field];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean" ? v : null;
    });
  }
  return { providerType: "local", columns };
}

export function positionsToGridOptions(
  overview: PortfolioOverview,
  callbacks: PositionsCallbacks,
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: false, strictHeights: false } },
    columnDefaults: {
      sorting: { enabled: false },
      cells: {
        events: {
          afterEdit(this: TableCell) {
            const colId = this.column?.id;
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker == null) return;
            const value = num(this.value);
            if (colId === "shares") {
              if (value !== null) callbacks.onEditShares(String(ticker), value);
            } else if (colId === "cost") {
              callbacks.onEditCost(String(ticker), value);
            }
          },
        },
      },
    },
    columns: positionsGridColumns(overview.aggregates, callbacks),
    data: positionsGridData(overview.positions),
  };
}
```

> Implementer note: `TableCell` is a named type export of `@highcharts/grid-pro` (verified) and has `.value`, `.column?.id`, `.row.getCell(...)` — so `afterEdit(this: TableCell)` and `click(this: TableCell)` should typecheck. If for any reason it does not, derive the `this` type via `ThisParameterType<NonNullable<NonNullable<NonNullable<NonNullable<Options["columnDefaults"]>["cells"]>["events"]>["afterEdit"]>>`. Do NOT guess a different API.

- [ ] **Step 4 — Run tests, confirm PASS.** Adjust test expectations only if the real `formatCurrency` output differs (e.g. `"+$200"`/`"$1,170"` formatting); the helper is source of truth — read `format.ts` and align.
- [ ] **Step 5 — Typecheck clean.** Resolve the `afterEdit` `this` typing per the implementer note.
- [ ] **Step 6 — Commit** `feat(grid): pure PortfolioOverview->Options positions adapter with cell editing`.

---

## Task 3: Migrar `PositionsTable` para o `DataGrid`

**Files:** Modify `frontend/src/components/portfolio/PortfolioOverviewView.tsx`

- [ ] **Step 1 — Read** the file; locate `PositionsTable`, `PositionRow`, `AddPositionRow`, `EditableValue`, `TH_BASE`/`TH_CLASS`, `formatShares`.

- [ ] **Step 2 — Wire callbacks + grid in `PositionsTable`:** Keep the existing `addMutation`/`editMutation`/`removeMutation`/`invalidate`. Add (with the other hooks, before any early return — there are none in PositionsTable; it returns a single section):

```tsx
  const queryClientLocal = queryClient; // already in scope
  const gridOptions = useMemo(
    () =>
      positionsToGridOptions(overview, {
        onEditShares: (ticker, value) => {
          if (Number.isFinite(value) && value > 0) {
            const pos = positions.find((p) => p.ticker === ticker);
            editMutation.mutate({ ticker, body: { quantity: value, acq_price: pos?.acq_price ?? null } });
          } else {
            queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] }); // revert
          }
        },
        onEditCost: (ticker, value) => {
          if (value === null || (Number.isFinite(value) && value > 0)) {
            const pos = positions.find((p) => p.ticker === ticker);
            if (pos) editMutation.mutate({ ticker, body: { quantity: pos.quantity, acq_price: value } });
          } else {
            queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] }); // revert
          }
        },
        onRemove: (ticker) => removeMutation.mutate(ticker),
      }),
    [overview, positions, portfolioId, editMutation, removeMutation, queryClient],
  );
```

Add imports at top of file: `useMemo` (from react), `import { DataGrid } from "@/components/ui/DataGrid";`, `import { positionsToGridOptions } from "@/lib/grid/positionsGridOptions";`.

- [ ] **Step 3 — Render:** Replace the `<div className="overflow-x-auto"><table>…</table></div>` block inside `PositionsTable` with the contiguous add-form + grid:

```tsx
      <AddPositionRowForm
        pending={addMutation.isPending}
        error={addMutation.error?.message ?? null}
        onAdd={async (ticker, body) => {
          try { await addMutation.mutateAsync({ ticker, body }); return true; }
          catch { return false; }
        }}
        onDirty={() => addMutation.reset()}
      />
      <div className="border-t border-border">
        <DataGrid options={gridOptions} className="min-h-[120px] w-full" />
      </div>
      {positions.length === 0 && (
        <p className="py-4 text-center text-[13px] text-text-muted">No positions yet — add one above.</p>
      )}
```

`AddPositionRowForm` is the existing `AddPositionRow` body re-housed as a small flex form (NOT a `<tr>`). Convert `AddPositionRow`'s `<tr>/<td>` markup into `<div>`s (a horizontal field row: ticker / cost / shares inputs + Add button), keeping its state/validation logic (`parseShares`/`parseCost`/`canAdd`/`submit`) unchanged. Rename to `AddPositionRowForm`.

- [ ] **Step 4 — Remove dead code:** delete `PositionRow`, `TH_BASE`, `TH_CLASS`. Keep `EditableValue` (still used by `PortfolioManageBar` for cash), `formatShares` (now also in the adapter — the local one in this file is still used? if not, remove it here and rely on the adapter's; check usages), `parseShares`/`parseCost`/`parseCash`, the footer (EOD/cash/total). Keep `KpiStrip`/`AllocationPanel`/`OverviewSection` untouched.

- [ ] **Step 5 — Verify:** `pnpm --dir frontend lint`, `pnpm --dir frontend typecheck`, `pnpm --dir frontend test` (all green).
- [ ] **Step 6 — Commit** `feat(portfolio): positions table via Highcharts Grid Pro with inline cell editing`.

---

## Task 4: Verificação integrada (build)
- [ ] `pnpm --dir frontend build` → `/` (portfolio) compila. Report sizes. Browser checks (owner): edit shares/cost (double-click → input → commit persists via PUT; invalid reverts), remove via ×, aggregates in P&L/Mkt headers, add-form adds, KPI/allocation intact, theme/dark-light.

## Self-Review
- Spec coverage: editable shares/cost (T2 editMode + T3 mutations), decorated read-only columns + aggregates-in-headers (T2), remove action (T2 click + T3 mutation), add-form contiguous (T3), CSS (T1), build (T4). ✓
- Placeholders: none except the explicitly-flagged `afterEdit` `this`-type resolution (with concrete fallback) and the "align test to real format.ts output" note.
- Type consistency: `positionsToGridOptions(overview, callbacks)`, `positionsGridColumns(aggregates, callbacks?)`, `positionsGridData(positions)`, `PositionsCallbacks`, `formatShares`, `escapeHtml` consistent across adapter/tests/migration; reuses `GRAPHITE_THEME`. CSS classes match formatter output.
