# Highcharts Grid Pro — Fundação + Screener (Plano 1/5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduzir o Highcharts Grid Pro no frontend com uma fundação reutilizável (token-bridge de tema Graphite + wrapper React + adapter de dados puro) e provar o conceito migrando a tabela do Screener (`ResultsTab`), mantendo ordenação/paginação/busca server-side já existentes.

**Architecture:** O grid é um **renderizador**; o estado (sort/dir/busca/página) e os dados continuam no **TanStack Query** (decisão do brainstorming). Uma função pura converte o payload `ScreenResults` em `Options` do Highcharts Grid; o evento `afterSort` do grid realimenta o estado React, que dispara o refetch server-side. O tema é puramente CSS: uma classe `.hcg-theme-graphite` mapeia as variáveis `--hcg-*` do grid para os tokens `--color-*`/`--ix-*` do design system, de modo que dark/light/densidade são herdados automaticamente (o grid é DOM, então `var()` resolve em tempo real).

**Tech Stack:** Next.js 15 (App Router, React 19), TypeScript, `@highcharts/grid-pro@3.0.0` (já instalado), TanStack Query v5, Tailwind 4, Vitest (testes de lógica pura — o projeto não usa Testing Library).

---

## Contexto de escopo — esta é a série de 5 planos da "migração ampla"

Cada plano produz software funcional e testável por si só. Todos reutilizam a fundação criada aqui.

1. **Plano 1 (este): Fundação do Grid + Screener** — token-bridge de tema, wrapper `DataGrid`, adapter puro, migração do `ResultsTab`.
2. **Plano 2: Lista de Funds** (`/funds`) — reusa a fundação; adapter para `FundsList`; sort/paginação/filtros server-side (`build_funds_select`).
3. **Plano 3: Portfolio positions + cell editing (Pro)** — `NumberInputRenderer`/`CellEditing` para editar shares/cost inline, persistindo via `putPosition`; agregados nos headers.
4. **Plano 4: Seletor de universo (multi-seleção)** — `CheckboxRenderer` para montar universos/watchlists (evolui o `UniverseCard`).
5. **Plano 5: Live ticks + scroll infinito + skeleton** — `useLiveTicks` nas células de preço das linhas visíveis; infinite-windowed fetch + virtual scrolling; skeleton no formato do grid.

**Trilha paralela (não bloqueante, infra):** diagnóstico de latência — medir TTFB prod (cold vs warm), revisar min-instances/keep-warm do InsForge compute, co-localização compute↔DB (`us-west-2`) e pool de conexões. Não é problema de SQL (queries de listagem rodam em 8–12 ms) nem de modelo de dados.

---

## Pré-requisitos (já satisfeitos)

- `@highcharts/grid-pro@3.0.0` instalado via pnpm (verificar: `pnpm --dir frontend ls @highcharts/grid-pro`).
- Comandos do projeto (a partir da raiz do repo): `pnpm --dir frontend test` (vitest run), `pnpm --dir frontend typecheck` (tsc --noEmit), `pnpm --dir frontend build`, `pnpm --dir frontend dev`.

## API do Highcharts Grid Pro usada neste plano (extraída dos tipos do pacote)

- Import: `import { grid, type Grid, type Column, type Options } from "@highcharts/grid-pro";` e CSS `import "@highcharts/grid-pro/css/grid-pro.css";`.
- Factory: `grid(renderTo: string | HTMLElement, options: Options): Grid`.
- Instância: `g.update(options: Options): Promise<void>`, `g.destroy(): void`, `g.showLoading(msg?)`, `g.hideLoading()`.
- `Options`: `{ rendering?: { theme?: string; rows?: { virtualization?: boolean; virtualizationThreshold?: number; strictHeights?: boolean } }, columnDefaults?: { sorting?: { enabled?: boolean }; events?: { afterSort?(this: Column): void } }, columns?: Array<{ id: string; header?: { format?: string }; className?: string; cells?: { formatter?(this: Cell): string }; sorting?: { order?: 'asc'|'desc'|null } }>, data?: { providerType: 'local'; columns: Record<string, Array<string|number|null>> } }`.
- No `afterSort`, `this` é a `Column`: leia `this.id` (string) e `this.options.sorting?.order` (`'asc'|'desc'|null`).
- `Cell.value` é o valor cru da célula (`string|number|boolean|null`).

## File Structure

- **Create** `frontend/src/lib/grid/grid-theme.css` — token-bridge `.hcg-theme-graphite` (mapeia `--hcg-*` → tokens Graphite) + classes de alinhamento de célula. Responsabilidade única: tematização.
- **Create** `frontend/src/lib/grid/gridOptions.ts` — adapter **puro** `ScreenResults → Options` (sem React, sem DOM). Responsabilidade única: transformar dados/estado em config do grid. Testável.
- **Create** `frontend/src/lib/grid/gridOptions.test.ts` — testes do adapter (Vitest, lógica pura).
- **Create** `frontend/src/components/ui/DataGrid.tsx` — wrapper React client fino (ciclo de vida do grid: create/update/destroy). Responsabilidade única: ponte React↔grid. Segue o padrão de `frontend/src/components/charts/EChart.tsx`.
- **Modify** `frontend/src/components/screener/ResultsTab.tsx` — substituir a `<table>` manual pelo `<DataGrid>`; manter header (título/matches/busca/export CSV) e footer (paginação server-side). Remover `ResultCell` e `CELL_CLASS` (a renderização passa a ser do grid).

> Decisão de teste: o projeto só tem Vitest (sem Testing Library/jsdom). Por isso o TDD recai sobre o adapter **puro** (`gridOptions.ts`). `DataGrid` e `ResultsTab` instanciam o grid (precisa de DOM real) e são validados por `typecheck` + `build` + verificação manual no browser. NÃO adicione Testing Library (YAGNI — o projeto deliberadamente não usa).

---

## Task 1: Token-bridge de tema Graphite (CSS)

**Files:**
- Create: `frontend/src/lib/grid/grid-theme.css`

- [ ] **Step 1: Criar o arquivo de tema**

Mapeia as variáveis reais do Grid Pro 3.0.0 (`--hcg-*`) para os tokens do design system. Como o grid é DOM, ao trocar `data-theme`/`data-density` no `<html>` os tokens `--color-*`/`--ix-*` mudam e o grid acompanha sem JavaScript.

```css
/*
 * Graphite token bridge for Highcharts Grid Pro.
 * Maps the grid's --hcg-* custom properties onto the project's design tokens
 * (globals.css @theme) so the grid inherits light/dark/density automatically.
 * Square, hairline, tabular — consistent with the Cockpit/Carbon tables.
 */
.hcg-theme-graphite {
  /* surfaces & text */
  --hcg-background: var(--color-surface-2);
  --hcg-color: var(--color-text-primary);
  --hcg-border-color: var(--color-border);
  --hcg-border-width: 1px;
  --hcg-border-radius: 0;
  --hcg-icon-border-radius: 0;

  /* density */
  --hcg-font-size: var(--ix-fs);
  --hcg-padding: 8px;
  --hcg-header-vertical-padding: 8px;
  --hcg-pagination-vertical-padding: 8px;

  /* rows */
  --hcg-row-even-background: var(--color-zebra);
  --hcg-row-hover-background: var(--color-accent-wash);

  /* focus / accent */
  --hcg-focus-ring-color: var(--color-accent);

  /* header/menu buttons */
  --hcg-button-color: var(--color-text-secondary);
  --hcg-button-hover-background: var(--color-layer-hover);
  --hcg-button-hover-color: var(--color-text-primary);
  --hcg-button-border-color: var(--color-border-strong);
  --hcg-button-border-radius: 0;

  /* inputs (filter / search / edit cells) */
  --hcg-input-border-color: var(--color-border-strong);
  --hcg-input-hover-border-color: var(--color-accent);
  --hcg-input-border-radius: 0;

  /* pagination selected page */
  --hcg-pagination-button-selected-background: var(--color-accent);
  --hcg-pagination-button-selected-color: var(--color-on-accent);
}

/* Numeric cells: right-aligned, tabular numerals (data-table convention). */
.hcg-theme-graphite .ix-grid-cell-num {
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.hcg-theme-graphite .ix-grid-cell-text {
  text-align: left;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/grid/grid-theme.css
git commit -m "feat(grid): Graphite token-bridge theme for Highcharts Grid Pro

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

> Verificação visual ocorre na Task 5 (a classe só tem efeito quando um grid é montado).

---

## Task 2: Adapter puro `ScreenResults → Options` (TDD)

**Files:**
- Create: `frontend/src/lib/grid/gridOptions.ts`
- Test: `frontend/src/lib/grid/gridOptions.test.ts`

- [ ] **Step 1: Escrever os testes (falhando)**

`frontend/src/lib/grid/gridOptions.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import type { ScreenResults } from "@/lib/api/client";
import {
  GRAPHITE_THEME,
  gridColumnsFromResults,
  gridDataFromResults,
  screenResultsToGridOptions,
} from "./gridOptions";

// Minimal ScreenResults stand-in (only fields the adapter reads).
const RESULTS = {
  columns: [
    { code: "ticker", name: "Ticker", data_type: "string" },
    { code: "sharpe_1y", name: "Sharpe 1Y", data_type: "number" },
  ],
  rows: [
    { ticker: "AAA", sharpe_1y: 1.23 },
    { ticker: "BBB", sharpe_1y: null },
  ],
  total: 2,
} as unknown as ScreenResults;

// `afterSort` reads only `this.id` and `this.options.sorting?.order`.
type ColumnLike = { id: string; options: { sorting?: { order?: "asc" | "desc" | null } } };
const fireAfterSort = (
  fn: ((this: never) => void) | undefined,
  ctx: ColumnLike,
) => (fn as unknown as (this: ColumnLike) => void).call(ctx);

describe("gridColumnsFromResults", () => {
  it("maps code→id, name→header, and aligns numeric vs text columns", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { dir: "asc" });
    expect(cols).toHaveLength(2);
    expect(cols[0]).toMatchObject({ id: "ticker", className: "ix-grid-cell-text" });
    expect(cols[1]).toMatchObject({ id: "sharpe_1y", className: "ix-grid-cell-num" });
  });

  it("marks only the active sort column with its order", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { sort: "sharpe_1y", dir: "desc" });
    expect(cols[1].sorting).toEqual({ order: "desc" });
    expect(cols[0].sorting).toBeUndefined();
  });

  it("formats numeric cells and renders an em-dash for null", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { dir: "asc" });
    const fmt = cols[1].cells?.formatter;
    expect((fmt as unknown as (this: { value: unknown }) => string).call({ value: null })).toBe("—");
    expect((fmt as unknown as (this: { value: unknown }) => string).call({ value: 1.23 })).toBe("1.23");
  });
});

describe("gridDataFromResults", () => {
  it("pivots rows into column-oriented arrays, null-safe", () => {
    const data = gridDataFromResults(RESULTS.columns, RESULTS.rows);
    expect(data).toEqual({
      providerType: "local",
      columns: { ticker: ["AAA", "BBB"], sharpe_1y: [1.23, null] },
    });
  });
});

describe("screenResultsToGridOptions", () => {
  it("applies the Graphite theme and enables virtualization", () => {
    const opts = screenResultsToGridOptions(RESULTS, { dir: "asc" }, { onSortChange: () => {} });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(opts.rendering?.rows?.virtualization).toBe(true);
  });

  it("afterSort calls onSortChange with the column id and the new order", () => {
    const onSortChange = vi.fn();
    const opts = screenResultsToGridOptions(RESULTS, { dir: "asc" }, { onSortChange });
    fireAfterSort(opts.columnDefaults?.events?.afterSort, {
      id: "sharpe_1y",
      options: { sorting: { order: "desc" } },
    });
    expect(onSortChange).toHaveBeenCalledWith("sharpe_1y", "desc");
  });

  it("afterSort is a no-op when the order already matches state (no refetch loop)", () => {
    const onSortChange = vi.fn();
    const opts = screenResultsToGridOptions(
      RESULTS,
      { sort: "sharpe_1y", dir: "desc" },
      { onSortChange },
    );
    fireAfterSort(opts.columnDefaults?.events?.afterSort, {
      id: "sharpe_1y",
      options: { sorting: { order: "desc" } },
    });
    expect(onSortChange).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `pnpm --dir frontend exec vitest run src/lib/grid/gridOptions.test.ts`
Expected: FAIL — `Failed to resolve import "./gridOptions"` (o módulo ainda não existe).

- [ ] **Step 3: Implementar o adapter**

`frontend/src/lib/grid/gridOptions.ts`:

```ts
/**
 * Pure adapter: turns the backend `ScreenResults` payload + current sort state
 * into a Highcharts Grid `Options` object. No React, no DOM — unit-tested.
 *
 * The grid renders; TanStack Query remains the data source. `afterSort` feeds
 * the column id + new order back to the caller, which re-fetches server-side.
 */
import type { Column, Options } from "@highcharts/grid-pro";

import type { ResultsColumn, ResultsRow, ScreenResults } from "@/lib/api/client";
import { formatMetricValue } from "@/lib/format";

export type SortDir = "asc" | "desc";

/** CSS class defined in grid-theme.css. */
export const GRAPHITE_THEME = "hcg-theme-graphite";

export interface GridSortState {
  sort?: string;
  dir: SortDir;
}

export interface GridCallbacks {
  onSortChange: (columnId: string, dir: SortDir) => void;
}

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;

/** Per-column cell formatter: text verbatim, numbers via the project formatter. */
function makeCellFormatter(dataType: string): CellFormatter {
  return function (this: GridCell): string {
    const value = this.value;
    if (value === null || value === undefined || value === "") return "—";
    if (dataType === "string") return String(value);
    return formatMetricValue(Number(value), dataType);
  };
}

/** Build the grid column definitions from the backend's dynamic columns. */
export function gridColumnsFromResults(
  columns: ResultsColumn[],
  state: GridSortState,
): GridColumns {
  return columns.map((col) => ({
    id: col.code,
    header: { format: col.name },
    className: col.data_type === "string" ? "ix-grid-cell-text" : "ix-grid-cell-num",
    cells: { formatter: makeCellFormatter(col.data_type) },
    ...(col.code === state.sort ? { sorting: { order: state.dir } } : {}),
  }));
}

/** Pivot the row objects into the grid's column-oriented `local` data block. */
export function gridDataFromResults(
  columns: ResultsColumn[],
  rows: ResultsRow[],
): NonNullable<Options["data"]> {
  const cols: Record<string, Array<string | number | null>> = {};
  for (const col of columns) {
    cols[col.code] = rows.map((row) => {
      const v = (row as Record<string, unknown>)[col.code];
      return typeof v === "number" || typeof v === "string" ? v : null;
    });
  }
  return { providerType: "local", columns: cols };
}

/** Full mapping: ScreenResults + sort state → grid Options. */
export function screenResultsToGridOptions(
  results: ScreenResults,
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
          // Guard: ignore the programmatic re-render that re-applies current state.
          if (
            (order === "asc" || order === "desc") &&
            !(this.id === state.sort && order === state.dir)
          ) {
            callbacks.onSortChange(this.id, order);
          }
        },
      },
    },
    columns: gridColumnsFromResults(results.columns, state),
    data: gridDataFromResults(results.columns, results.rows),
  };
}
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pnpm --dir frontend exec vitest run src/lib/grid/gridOptions.test.ts`
Expected: PASS (todos os `describe`/`it` verdes).

- [ ] **Step 5: Typecheck**

Run: `pnpm --dir frontend typecheck`
Expected: sem erros (confirma que os tipos derivados de `Options` e `Column` casam com a API do pacote).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/grid/gridOptions.ts frontend/src/lib/grid/gridOptions.test.ts
git commit -m "feat(grid): pure ScreenResults→Options adapter with afterSort wiring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wrapper React `DataGrid`

**Files:**
- Create: `frontend/src/components/ui/DataGrid.tsx`

- [ ] **Step 1: Implementar o wrapper**

Segue o padrão de `EChart.tsx`: cria na montagem, faz `update` quando `options` muda, `destroy` no unmount. Import dinâmico do pacote mantém o grid fora do SSR; o CSS é importado estaticamente (seguro em client component). O pai deve **memoizar** `options` (a Task 4 faz isso) para evitar updates supérfluos.

```tsx
"use client";

/**
 * Thin Highcharts Grid Pro wrapper: create in a ref on mount, update on option
 * change, destroy on unmount. The grid lib is dynamically imported so it never
 * runs during SSR. All grid content comes from the pure adapter in
 * `src/lib/grid/gridOptions.ts`. Mirrors the EChart wrapper.
 */
import { useEffect, useRef } from "react";
import type { Grid, Options } from "@highcharts/grid-pro";

import "@highcharts/grid-pro/css/grid-pro.css";
import "@/lib/grid/grid-theme.css";

export function DataGrid({
  options,
  className,
}: {
  options: Options;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<Grid | null>(null);
  // Keep the freshest options for the async create callback without re-running it.
  const latestOptions = useRef(options);
  latestOptions.current = options;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void import("@highcharts/grid-pro").then(({ grid }) => {
      if (disposed || !containerRef.current) return;
      gridRef.current = grid(containerRef.current, latestOptions.current);
    });
    return () => {
      disposed = true;
      gridRef.current?.destroy();
      gridRef.current = null;
    };
  }, []);

  useEffect(() => {
    void gridRef.current?.update(options);
  }, [options]);

  return <div ref={containerRef} className={className} />;
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm --dir frontend typecheck`
Expected: sem erros (valida o import de `grid`/`Grid`/`Options` e o uso de `update`/`destroy`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/DataGrid.tsx
git commit -m "feat(grid): DataGrid React wrapper over Highcharts Grid Pro

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Migrar `ResultsTab` para o `DataGrid`

**Files:**
- Modify: `frontend/src/components/screener/ResultsTab.tsx`

Mantém intactos: estado (`sort`/`dir`/`searchText`/`search`/`page`), a query `resultsQuery` (com `keepPreviousData`), o cabeçalho (título, badge de matches, busca, export CSV) e o rodapé de paginação (`pageWindow`). Substitui apenas o miolo `<div className="overflow-x-auto"><table>…</table></div>` pelo `<DataGrid>`. Remove `ResultCell`, `CELL_CLASS` e o `Link`/`Image`-free render manual de células (agora é o grid quem renderiza).

- [ ] **Step 1: Ajustar imports e estado**

Em `frontend/src/components/screener/ResultsTab.tsx`, adicione os imports do wrapper e do adapter, e remova os que deixam de ser usados.

Adicionar (junto aos imports existentes):

```ts
import { useMemo } from "react";
import { DataGrid } from "@/components/ui/DataGrid";
import { screenResultsToGridOptions } from "@/lib/grid/gridOptions";
```

Observações de import:
- Some o uso de `ResultsColumn`/`ResultsRow` diretos no JSX (o adapter os consome). Mantenha-os importados apenas se ainda referenciados; caso contrário, remova-os do import de `@/lib/api/client`.
- O `type SortDir = "asc" | "desc"` local pode permanecer; ele é estruturalmente idêntico ao `SortDir` exportado pelo adapter.

- [ ] **Step 2: Construir as `options` memoizadas dentro de `ResultsTab`**

Logo após o bloco que desestrutura `const { columns, rows, total } = resultsQuery.data;` (e antes do `return`), adicione:

```ts
  const gridOptions = useMemo(
    () =>
      screenResultsToGridOptions(
        resultsQuery.data,
        { sort, dir },
        {
          onSortChange: (columnId, order) => {
            setSort(columnId);
            setDir(order);
            setPage(1);
          },
        },
      ),
    // resultsQuery.data changes per page/sort/search fetch; sort/dir mark the active column.
    [resultsQuery.data, sort, dir],
  );
```

> `setSort`/`setDir`/`setPage` são setters estáveis do `useState`; não precisam entrar nas deps. O guard do `afterSort` (Task 2) impede laço de refetch quando o update reaplica o mesmo estado.

- [ ] **Step 3: Substituir a tabela pelo grid**

Localize o bloco de renderização da tabela (o `<div className={\`overflow-x-auto …\`}>` contendo `<table className="w-full min-w-[760px] …">…</table>`) e substitua-o inteiro por:

```tsx
      <div
        className={`transition-opacity ${resultsQuery.isFetching ? "opacity-60" : ""}`}
      >
        <DataGrid options={gridOptions} className="h-[560px] w-full" />
      </div>
```

A altura fixa (`h-[560px]`) é necessária para o virtual scrolling do grid. Mantenha o cabeçalho (acima) e o rodapé de paginação (abaixo) exatamente como estão.

- [ ] **Step 4: Remover código morto**

Remova a função `ResultCell` e a constante `CELL_CLASS` (não são mais referenciadas). Mantenha `pageWindow`, `PAGE_SIZE`, `formatCompact` (ainda usados no rodapé/cabeçalho).

- [ ] **Step 5: Typecheck + testes existentes**

Run: `pnpm --dir frontend typecheck`
Expected: sem erros.

Run: `pnpm --dir frontend test`
Expected: PASS — toda a suíte existente (incluindo `gridOptions.test.ts`) verde; nenhuma regressão.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/screener/ResultsTab.tsx
git commit -m "feat(screener): render results via Highcharts Grid Pro (DataGrid)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Verificação integrada (build + browser)

**Files:** nenhum (verificação).

- [ ] **Step 1: Build de produção**

Run: `pnpm --dir frontend build`
Expected: build conclui sem erros (valida que o import dinâmico do grid e o CSS não quebram o bundler/SSR do Next).

- [ ] **Step 2: Subir o dev server e abrir o Screener**

Run: `pnpm --dir frontend dev` (deixe rodando)
Abra o app, vá ao Screener, selecione/abra um screen com resultados (aba Results).

- [ ] **Step 3: Checklist visual e funcional (manual)**

Confirme:
- O grid usa o visual Graphite (fundo `surface-2`, bordas hairline, zebra, cantos retos, números tabulares à direita; sem o tema azul padrão do Highcharts).
- Alternar `data-theme` light/dark (pelo toggle do app) muda o grid junto, sem reload.
- Clicar num header reordena: a requisição refaz server-side (Network mostra `?sort=<code>&dir=…`) e a 1ª página volta ordenada.
- A busca (debounce 300 ms), a paginação (rodapé) e o Export CSV continuam funcionando.
- Sem erro de licença bloqueando (Grid Pro mostra apenas um aviso de licença em DEV — esperado até adquirir a licença).

- [ ] **Step 4: Registrar resultado**

Se tudo passar, a fundação está validada. Se o tema não aplicar, confira se o `className` do container do grid recebeu `hcg-theme-graphite` (o adapter define `rendering.theme`); se o sort não refetch, confirme empiricamente onde o Grid Pro expõe a ordem no `afterSort` (`this.options.sorting?.order`) e ajuste o adapter — este é o único ponto da API validado só em runtime.

---

## Self-Review

**1. Cobertura do spec (design aprovado):**
- Requisito 1 (tema Graphite, dark/light): Task 1 (token-bridge) + `rendering.theme` no adapter. ✓
- Requisito 2 (sort/paginação server-side via TanStack): `afterSort` → estado → refetch; paginação server-side mantida. ✓ (este plano)
- Requisito 5 (virtual scrolling): habilitado (`rendering.rows.virtualization`); scroll infinito real é o Plano 5. Parcial por desenho (YAGNI agora). ✓
- Requisitos 3 (filtros dinâmicos), 4 (WebSocket/live ticks), entrada de dados (cell editing) e seletor de universo: **fora deste plano** — Planos 2–5. Documentado na seção de série.

**2. Placeholders:** nenhum "TBD"/"TODO". Todo passo de código tem código completo. O único item validável-só-em-runtime (leitura da ordem no `afterSort`) está explicitado na Task 5 com o fallback.

**3. Consistência de tipos:** `SortDir`, `GridSortState`, `GridCallbacks`, `screenResultsToGridOptions(results, state, callbacks)`, `gridColumnsFromResults(columns, state)`, `gridDataFromResults(columns, rows)`, `GRAPHITE_THEME` e as classes `ix-grid-cell-num`/`ix-grid-cell-text` são usados de forma idêntica no adapter, nos testes, no CSS e no `ResultsTab`. Imports do pacote (`grid`, `Grid`, `Column`, `Options`) conferem com os exports verificados em `es-modules/masters/grid-pro.src.d.ts`.

---

## Execution Handoff

**Plano salvo em `docs/superpowers/plans/2026-06-13-highcharts-grid-foundation-screener.md`.**

Este é o **Plano 1 de 5** da migração ampla. Posso gerar os Planos 2–5 (Funds, Portfolio+edição, Universo multi-seleção, Live ticks/infinite/skeleton) na mesma qualidade quando você quiser — cada um curto, pois reusam a fundação criada aqui.
