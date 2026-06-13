# Highcharts Grid Pro — Lista de Funds (Plano 2/5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Migrar a tabela do universo de Funds (`FundsView`) para o `DataGrid` (Highcharts Grid Pro), reusando a fundação do Plano 1, mantendo o painel de filtros, busca, ordenação/paginação server-side e export CSV.

**Architecture:** Mesma do Plano 1 — grid renderiza; TanStack Query é a fonte. Um adapter PURO `fundsListToGridOptions(data, state, callbacks)` constrói as 12 colunas fixas com renderizadores de célula bespoke (links para o perfil do fundo, tag de tipo, coloração de sinal no retorno, check de elite, numéricos formatados) e fia o `afterSort` para refetch server-side. Reusa `GRAPHITE_THEME`, `SortDir`, `GridSortState`, `GridCallbacks` de `gridOptions.ts` e o wrapper `DataGrid`.

**Tech Stack:** Next 15/React 19, TS, `@highcharts/grid-pro@3.0.0`, TanStack Query v5, Vitest (lógica pura).

**Branch:** `feat/highcharts-grid-rollout` (já criada a partir da main pós-merge).

---

## Contexto (fatos verificados)
- `FundsView` (`frontend/src/components/funds/FundsView.tsx`) tem um painel de filtros (search/type/asset-class/strategy/bounds — PERMANECE) e um componente filho `FundsTable` que renderiza a `<table>` manual (`COLUMNS`, `FundRow`, `CELL_CLASS`, `signTone`, `pageWindow`). `FundsTable` só é renderizado quando `data` existe (após os early-returns de `isPending`/`isError` no pai) → **o `useMemo` das opções do grid vive dentro de `FundsTable`, sem risco de Rules-of-Hooks.**
- `FundListItem` (de `@/lib/api/client`) tem: `instrument_id` (string), `ticker` (string|null), `name` (string), `fund_type` (string), `strategy_label` (string|null), `asset_class` (string|null), `aum_usd`/`expense_ratio`/`return_1y`/`volatility_1y`/`sharpe_1y`/`peer_sharpe_pctl` (number|null), `elite_flag` (boolean).
- `FundsList` = `{ items: FundListItem[]; total: number; staleness: {...}; classification_note: string; page; page_size }`.
- Colunas ordenáveis (códigos do whitelist do backend, já validados em `FundsView`): `ticker, name, fund_type, strategy_label, asset_class, aum_usd, expense_ratio, return_1y, volatility_1y, sharpe_1y, peer_sharpe_pctl, elite_flag`. Numéricas ordenam desc-primeiro; texto asc-primeiro (replicado via `sorting.orderSequence` por coluna).
- **API do Grid Pro (verificada nos .d.ts):** cell `formatter: (this: Cell) => string` retorna HTML; `Cell.value` é o valor cru; `Cell.row` é a `Row`; `Row.getCell(columnId): Cell | undefined` dá acesso a células irmãs (usado para montar o href com `instrument_id`). Coluna pode ser ocultada com `enabled: false` (continua presente nos dados/cells, logo `getCell` funciona). `sorting.orderSequence: ('asc'|'desc'|null)[]`.

## File Structure
- **Create** `frontend/src/lib/grid/fundsGridOptions.ts` — adapter PURO + formatters (responsabilidade única; testável).
- **Create** `frontend/src/lib/grid/fundsGridOptions.test.ts` — testes do adapter.
- **Modify** `frontend/src/lib/grid/grid-theme.css` — adicionar classes de célula usadas pelos formatters (`ix-grid-link`, `ix-grid-link-plain`, `ix-grid-trunc`, `ix-grid-tag`, `ix-grid-elite`).
- **Modify** `frontend/src/components/funds/FundsView.tsx` — `FundsTable` renderiza via `DataGrid`; `onSort` (toggle) vira `onSortChange(code, dir)`; remover `COLUMNS`/`FundRow`/`CELL_CLASS`/`signTone`/`TYPE_TAG`/`ASSET_CLASS_LABEL` (migram para o adapter); manter filtros, header, footer (`pageWindow`), export.

> Decisão de fidelidade: a barra visual de `peer_sharpe_pctl` (que usava `style="width:%"` inline) é substituída pelo número (`formatNumber(n,0)`) para evitar dependência de `style` inline no HTML do formatter (sanitização AST). Valor preservado; barra é decorativa. Restaurável depois se o AST do grid aceitar `style` inline (a confirmar no browser).

---

## Task 1: Classes de célula no tema (CSS)

**Files:** Modify `frontend/src/lib/grid/grid-theme.css`

- [ ] **Step 1:** Acrescentar ao FINAL de `frontend/src/lib/grid/grid-theme.css` (após as regras `.ix-grid-cell-*` existentes) EXATAMENTE:

```css

/* Funds cell renderers (used by fundsGridOptions formatters). */
.hcg-theme-graphite .ix-grid-link {
  font-weight: 700;
  color: var(--color-accent);
}
.hcg-theme-graphite .ix-grid-link:hover { text-decoration: underline; }
.hcg-theme-graphite .ix-grid-link-plain { color: var(--color-text-primary); text-decoration: none; }
.hcg-theme-graphite .ix-grid-link-plain:hover { text-decoration: underline; }
.hcg-theme-graphite .ix-grid-trunc {
  display: inline-block;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.hcg-theme-graphite .ix-grid-tag {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border: 1px solid var(--color-border-strong);
  background: var(--color-field);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
}
.hcg-theme-graphite .ix-grid-elite { color: var(--color-accent); font-weight: 700; }
```

- [ ] **Step 2:** Commit.
```bash
cd /e/investintell-light
git add frontend/src/lib/grid/grid-theme.css
git commit -m "feat(grid): cell-renderer classes for the Funds grid

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Adapter `fundsListToGridOptions` (TDD)

**Files:** Create `frontend/src/lib/grid/fundsGridOptions.ts` + `frontend/src/lib/grid/fundsGridOptions.test.ts`

- [ ] **Step 1 — Test (failing)** `frontend/src/lib/grid/fundsGridOptions.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import type { FundsList } from "@/lib/api/client";
import {
  escapeHtml,
  fundsGridColumns,
  fundsGridData,
  fundsListToGridOptions,
} from "./fundsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

const ITEMS = [
  {
    instrument_id: "uuid-1",
    ticker: "AAA",
    name: "Alpha <Equity> Fund",
    fund_type: "etf",
    strategy_label: "Large Cap",
    asset_class: "equity",
    aum_usd: 1_000_000,
    expense_ratio: 0.005,
    return_1y: 0.123,
    volatility_1y: 0.2,
    sharpe_1y: 1.1,
    peer_sharpe_pctl: 87,
    elite_flag: true,
  },
  {
    instrument_id: "uuid-2",
    ticker: null,
    name: "Beta Fund",
    fund_type: "mutual_fund",
    strategy_label: null,
    asset_class: null,
    aum_usd: null,
    expense_ratio: null,
    return_1y: -0.04,
    volatility_1y: null,
    sharpe_1y: null,
    peer_sharpe_pctl: null,
    elite_flag: false,
  },
] as unknown as FundsList["items"];

const LIST = { items: ITEMS, total: 2 } as unknown as FundsList;

// Mock Cell `this`: value + row.getCell(id).value
type CellLike = { value: unknown; row: { getCell: (id: string) => { value: unknown } | undefined } };
const fmtCall = (
  fn: unknown,
  value: unknown,
  rowValues: Record<string, unknown> = {},
): string =>
  (fn as (this: CellLike) => string).call({
    value,
    row: { getCell: (id: string) => (id in rowValues ? { value: rowValues[id] } : undefined) },
  });

describe("escapeHtml", () => {
  it("escapes &, <, >, and quotes", () => {
    expect(escapeHtml('a & b <c> "d"')).toBe("a &amp; b &lt;c&gt; &quot;d&quot;");
  });
});

describe("fundsGridColumns", () => {
  it("returns the 12 display columns plus a hidden instrument_id column", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    expect(cols).toHaveLength(13);
    const ids = cols.map((c) => c.id);
    expect(ids).toContain("instrument_id");
    const hidden = cols.find((c) => c.id === "instrument_id");
    expect(hidden?.enabled).toBe(false);
  });

  it("aligns numeric vs text and sets per-type orderSequence", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const ticker = cols.find((c) => c.id === "ticker");
    const aum = cols.find((c) => c.id === "aum_usd");
    expect(ticker?.className).toBe("ix-grid-cell-text");
    expect(aum?.className).toBe("ix-grid-cell-num");
    expect(ticker?.sorting?.orderSequence).toEqual(["asc", "desc", null]);
    expect(aum?.sorting?.orderSequence).toEqual(["desc", "asc", null]);
  });

  it("marks only the active sort column with its order", () => {
    const cols = fundsGridColumns({ sort: "aum_usd", dir: "desc" });
    expect(cols.find((c) => c.id === "aum_usd")?.sorting?.order).toBe("desc");
    expect(cols.find((c) => c.id === "ticker")?.sorting?.order).toBeUndefined();
  });

  it("ticker formatter builds an escaped link to the fund profile using instrument_id from the row", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    expect(fmtCall(fmt, "AAA", { instrument_id: "uuid-1" })).toBe(
      '<a class="ix-grid-link" href="/funds/uuid-1">AAA</a>',
    );
    // no instrument_id -> plain label
    expect(fmtCall(fmt, "AAA", {})).toBe("AAA");
  });

  it("name formatter escapes HTML and wraps in a truncating link", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const fmt = cols.find((c) => c.id === "name")!.cells!.formatter;
    expect(fmtCall(fmt, "Alpha <Equity> Fund", { instrument_id: "uuid-1" })).toBe(
      '<a class="ix-grid-link-plain" href="/funds/uuid-1"><span class="ix-grid-trunc">Alpha &lt;Equity&gt; Fund</span></a>',
    );
  });

  it("type/asset/aum/return/sharpe/peer/elite formatters render expected output", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const get = (id: string) => cols.find((c) => c.id === id)!.cells!.formatter;
    expect(fmtCall(get("fund_type"), "etf")).toBe('<span class="ix-grid-tag">ETF</span>');
    expect(fmtCall(get("asset_class"), "equity")).toBe("Equity");
    expect(fmtCall(get("asset_class"), null)).toBe("—");
    expect(fmtCall(get("aum_usd"), 1_000_000)).toBe("$1.0M");
    expect(fmtCall(get("aum_usd"), null)).toBe("—");
    expect(fmtCall(get("return_1y"), 0.123)).toBe('<span class="text-gain">+12.30%</span>');
    expect(fmtCall(get("return_1y"), -0.04)).toBe('<span class="text-loss">-4.00%</span>');
    expect(fmtCall(get("sharpe_1y"), 1.1)).toBe("1.10");
    expect(fmtCall(get("peer_sharpe_pctl"), 87)).toBe("87");
    expect(fmtCall(get("elite_flag"), true)).toBe('<span class="ix-grid-elite" aria-label="Elite fund">✓</span>');
    expect(fmtCall(get("elite_flag"), false)).toBe('<span class="text-text-muted">—</span>');
  });
});

describe("fundsGridData", () => {
  it("pivots items into column arrays including instrument_id, null-safe", () => {
    const data = fundsGridData(ITEMS);
    expect(data.providerType).toBe("local");
    expect(data.columns.ticker).toEqual(["AAA", null]);
    expect(data.columns.instrument_id).toEqual(["uuid-1", "uuid-2"]);
    expect(data.columns.elite_flag).toEqual([true, false]);
    expect(data.columns.aum_usd).toEqual([1_000_000, null]);
  });
});

describe("fundsListToGridOptions", () => {
  it("applies theme + virtualization and wires afterSort with the loop guard", () => {
    const onSortChange = vi.fn();
    const opts = fundsListToGridOptions(LIST, { sort: "aum_usd", dir: "desc" }, { onSortChange });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(opts.rendering?.rows?.virtualization).toBe(true);
    const afterSort = opts.columnDefaults?.events?.afterSort as unknown as (this: {
      id: string;
      options: { sorting?: { order?: "asc" | "desc" | null } };
    }) => void;
    // matches current state -> no-op
    afterSort.call({ id: "aum_usd", options: { sorting: { order: "desc" } } });
    expect(onSortChange).not.toHaveBeenCalled();
    // changed -> fires
    afterSort.call({ id: "sharpe_1y", options: { sorting: { order: "asc" } } });
    expect(onSortChange).toHaveBeenCalledWith("sharpe_1y", "asc");
  });
});
```

- [ ] **Step 2 — Run, confirm FAIL:** `pnpm --dir frontend exec vitest run src/lib/grid/fundsGridOptions.test.ts`

- [ ] **Step 3 — Implement** `frontend/src/lib/grid/fundsGridOptions.ts`:

```ts
/**
 * Pure adapter: FundsList -> Highcharts Grid Pro Options for the Funds universe.
 * Fixed columns with bespoke cell renderers (profile links, type tag, sign-
 * coloured return, elite check, formatted numerics). Pure (no React/DOM) and
 * unit-tested. Reuses the shared theme/sort types from gridOptions.ts.
 */
import type { Column, Options } from "@highcharts/grid-pro";

import type { FundsList } from "@/lib/api/client";
import { formatCompact, formatNumber, formatPercent } from "@/lib/format";
import {
  GRAPHITE_THEME,
  type GridCallbacks,
  type GridSortState,
} from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type SortOrder = NonNullable<
  NonNullable<NonNullable<GridColumns[number]["sorting"]>["orderSequence"]>[number]
>;

const TYPE_TAG: Record<string, string> = { etf: "ETF", mutual_fund: "MF", mmf: "MMF" };
const ASSET_CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
};

const NUM_SEQ: SortOrder[] = ["desc", "asc", null];
const TEXT_SEQ: SortOrder[] = ["asc", "desc", null];

/** All FundListItem keys we feed to the grid (display columns + hidden id). */
const DATA_KEYS = [
  "ticker", "name", "fund_type", "strategy_label", "asset_class",
  "aum_usd", "expense_ratio", "return_1y", "volatility_1y", "sharpe_1y",
  "peer_sharpe_pctl", "elite_flag", "instrument_id",
] as const;

/** Escape text destined for a cell's HTML formatter output. */
export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fundHref(row: GridCell["row"]): string | null {
  const id = row.getCell("instrument_id")?.value;
  return id === null || id === undefined ? null : `/funds/${encodeURIComponent(String(id))}`;
}

/** number|null -> "—" or fn(n). */
function numOrDash(value: unknown, fn: (n: number) => string): string {
  return value === null || value === undefined || value === "" ? "—" : fn(Number(value));
}

function tickerFormatter(this: GridCell): string {
  const label = escapeHtml(this.value ?? "—");
  const href = fundHref(this.row);
  return href ? `<a class="ix-grid-link" href="${href}">${label}</a>` : label;
}

function nameFormatter(this: GridCell): string {
  const inner = `<span class="ix-grid-trunc">${escapeHtml(this.value ?? "")}</span>`;
  const href = fundHref(this.row);
  return href ? `<a class="ix-grid-link-plain" href="${href}">${inner}</a>` : inner;
}

function typeFormatter(this: GridCell): string {
  const v = String(this.value ?? "");
  return `<span class="ix-grid-tag">${escapeHtml(TYPE_TAG[v] ?? v)}</span>`;
}

function assetClassFormatter(this: GridCell): string {
  const v = this.value;
  if (v === null || v === undefined || v === "") return "—";
  return escapeHtml(ASSET_CLASS_LABEL[String(v)] ?? String(v));
}

function strategyFormatter(this: GridCell): string {
  return `<span class="ix-grid-trunc">${escapeHtml(this.value ?? "")}</span>`;
}

function returnFormatter(this: GridCell): string {
  const v = this.value;
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  const cls = n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
  const text = escapeHtml(formatPercent(n, 2, { signed: true }));
  return `<span class="${cls}">${text}</span>`;
}

function eliteFormatter(this: GridCell): string {
  return this.value
    ? `<span class="ix-grid-elite" aria-label="Elite fund">✓</span>`
    : `<span class="text-text-muted">—</span>`;
}

interface FundColSpec {
  id: string;
  label: string;
  numeric: boolean;
  formatter: CellFormatter;
}

const FUND_COLUMNS: FundColSpec[] = [
  { id: "ticker", label: "Ticker", numeric: false, formatter: tickerFormatter },
  { id: "name", label: "Name", numeric: false, formatter: nameFormatter },
  { id: "fund_type", label: "Type", numeric: false, formatter: typeFormatter },
  { id: "strategy_label", label: "Strategy", numeric: false, formatter: strategyFormatter },
  { id: "asset_class", label: "Asset class", numeric: false, formatter: assetClassFormatter },
  { id: "aum_usd", label: "AUM", numeric: true, formatter(this: GridCell) { return numOrDash(this.value, (n) => `$${formatCompact(n)}`); } },
  { id: "expense_ratio", label: "Expense", numeric: true, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatPercent(n)); } },
  { id: "return_1y", label: "Return 1Y", numeric: true, formatter: returnFormatter },
  { id: "volatility_1y", label: "Vol 1Y", numeric: true, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatPercent(n)); } },
  { id: "sharpe_1y", label: "Sharpe 1Y", numeric: true, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatNumber(n)); } },
  { id: "peer_sharpe_pctl", label: "Peer pctl", numeric: true, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatNumber(n, 0)); } },
  { id: "elite_flag", label: "Elite", numeric: true, formatter: eliteFormatter },
];

export function fundsGridColumns(state: GridSortState): GridColumns {
  const cols: GridColumns = FUND_COLUMNS.map((c) => ({
    id: c.id,
    header: { format: c.label },
    className: c.numeric ? "ix-grid-cell-num" : "ix-grid-cell-text",
    cells: { formatter: c.formatter },
    sorting: {
      orderSequence: c.numeric ? NUM_SEQ : TEXT_SEQ,
      ...(c.id === state.sort ? { order: state.dir } : {}),
    },
  }));
  cols.push({ id: "instrument_id", enabled: false });
  return cols;
}

export function fundsGridData(items: FundsList["items"]): NonNullable<Options["data"]> {
  const columns: Record<string, Array<string | number | boolean | null>> = {};
  for (const key of DATA_KEYS) {
    columns[key] = items.map((it) => {
      const v = (it as Record<string, unknown>)[key];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean"
        ? v
        : null;
    });
  }
  return { providerType: "local", columns };
}

export function fundsListToGridOptions(
  data: FundsList,
  state: GridSortState,
  callbacks: GridCallbacks,
): Options {
  return {
    rendering: {
      theme: GRAPHITE_THEME,
      rows: { virtualization: true, virtualizationThreshold: 100, strictHeights: true },
    },
    columnDefaults: {
      sorting: { enabled: true },
      events: {
        afterSort(this: Column) {
          const order = this.options.sorting?.order;
          if (
            (order === "asc" || order === "desc") &&
            !(this.id === state.sort && order === state.dir)
          ) {
            callbacks.onSortChange(this.id, order);
          }
        },
      },
    },
    columns: fundsGridColumns(state),
    data: fundsGridData(data.items),
  };
}
```

- [ ] **Step 4 — Run, confirm PASS:** `pnpm --dir frontend exec vitest run src/lib/grid/fundsGridOptions.test.ts`
- [ ] **Step 5 — Typecheck:** `pnpm --dir frontend typecheck` (clean). If `formatPercent`/`formatNumber`/`formatCompact` signatures differ from `(n: number, decimals?, opts?)`, read `frontend/src/lib/format.ts` and adjust the calls (do NOT guess).
- [ ] **Step 6 — Commit:**
```bash
cd /e/investintell-light
git add frontend/src/lib/grid/fundsGridOptions.ts frontend/src/lib/grid/fundsGridOptions.test.ts
git commit -m "feat(grid): pure FundsList->Options adapter (fixed columns + renderers)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Migrar `FundsView` para o `DataGrid`

**Files:** Modify `frontend/src/components/funds/FundsView.tsx`

- [ ] **Step 1 — Imports:** Add `useMemo` to the react import; add `import { DataGrid } from "@/components/ui/DataGrid";` and `import { fundsListToGridOptions } from "@/lib/grid/fundsGridOptions";`. Remove `Link` (no longer used once `FundRow` is gone), and `formatNumber`/`formatPercent` if they become unused (keep `formatCompact`/`formatDate` — still used by the meta line/header). Let `lint`/`typecheck` confirm unused imports.

- [ ] **Step 2 — Replace the toggle handler:** In `FundsView`, replace the `onSort` function with a direct setter (the grid toggles internally and reports the resulting order via `afterSort`):

```tsx
  const onSortChange = (code: string, nextDir: SortDir) => {
    setSort(code);
    setDir(nextDir);
    setPage(1);
  };
```

Update the `<FundsTable ... />` usage: replace the `onSort={onSort}` prop with `onSortChange={onSortChange}`.

- [ ] **Step 3 — Rework `FundsTable`:** Change its props type: replace `onSort: (code: string) => void;` with `onSortChange: (code: string, dir: SortDir) => void;`. Inside `FundsTable` (where `const { items, total } = data;` is — `data` is always defined here), add the grid options memo and replace the table:

```tsx
  const gridOptions = useMemo(
    () => fundsListToGridOptions(data, { sort, dir }, { onSortChange }),
    [data, sort, dir, onSortChange],
  );
```

Replace the entire `<div className="overflow-x-auto ...">…<table>…</table></div>` block with:

```tsx
      <div className={`transition-opacity ${isFetching ? "opacity-60" : ""}`}>
        <DataGrid options={gridOptions} className="h-[600px] w-full" />
      </div>
```

Keep the header (Universe title / matches badge / Export CSV), the `exportError` alert, and the footer (`pageWindow` pagination + `classification_note`) exactly as they are.

- [ ] **Step 4 — Remove dead code:** Delete `COLUMNS`, `FundRow`, `CELL_CLASS`, `signTone`, `TYPE_TAG`, `ASSET_CLASS_LABEL` (the last two now live in the adapter; `ASSET_CLASSES`/`FUND_TYPES` used by the filter dropdowns STAY). Keep `pageWindow`, `PAGE_SIZE`, `BoundField`, `parseBound`, the filter panel, the query, the export logic.

> Note: `onSortChange` is referenced in the memo deps. Since it's recreated each render in the parent, either wrap it in `useCallback` in `FundsView` OR (simpler) define `onSortChange` inline where passed and keep the memo dep — to avoid needless re-memo, wrap it: in `FundsView` use `const onSortChange = useCallback((code: string, nextDir: SortDir) => { setSort(code); setDir(nextDir); setPage(1); }, []);` (import `useCallback`). Setters are stable, so `[]` deps are correct.

- [ ] **Step 5 — Verify:** `pnpm --dir frontend lint` (clean — Rules of Hooks/unused), `pnpm --dir frontend typecheck` (clean), `pnpm --dir frontend test` (green).
- [ ] **Step 6 — Commit:**
```bash
cd /e/investintell-light
git add frontend/src/components/funds/FundsView.tsx
git commit -m "feat(funds): render the funds universe via Highcharts Grid Pro (DataGrid)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Verificação integrada (build)

- [ ] **Step 1:** `pnpm --dir frontend build` → succeeds (`/funds` compiles).
- [ ] **Step 2:** Report the `/funds` route size + that lint/typecheck/test/build are all green. Browser visual check (theme, links to `/funds/{id}`, sorting refetch, filters, pagination, export) is the owner's manual step.

---

## Self-Review (run after writing)
- **Spec coverage:** theme classes (T1), pure adapter with all 12 renderers + hidden id + afterSort guard (T2), FundsView migration with correct hook placement inside FundsTable (T3), build (T4). ✓
- **Placeholders:** none — verbatim code in every step; the only conditional is the `format.ts` signature check (with explicit "read, don't guess" instruction).
- **Type consistency:** reuses `GridSortState`/`GridCallbacks`/`GRAPHITE_THEME` from `gridOptions.ts`; `fundsListToGridOptions(data, state, callbacks)`, `fundsGridColumns(state)`, `fundsGridData(items)`, `escapeHtml` used identically across adapter/tests/migration. Classes `ix-grid-*` defined in T1 match those emitted by the formatters in T2.
