# Highcharts Grid Pro — Live ticks + Infinite/Virtual + Skeleton + Empty-state (Plano 5/5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (Opus 4.8). Steps use `- [ ]`.
> **WORKTREE-ONLY:** execute this ENTIRELY inside the dedicated worktree `E:/investintell-light-grid` (branch `feat/highcharts-grid-rollout`). NEVER touch `E:/investintell-light` (the main working tree, on `main`, used in parallel). All `pnpm`/git commands run with cwd inside the worktree.

**Goal:** Fechar o rollout do grid com 4 melhorias de UX/realtime: (A) **empty-state** genérico no `DataGrid`; (B) **skeleton** no formato do grid no primeiro load; (C) **infinite-windowed virtual scrolling** para funds/screener; (D) **live ticks** nas células de preço (reusa `useLiveTicks` + worker WS no Railway já existente).

**Architecture:** Reusa toda a fundação dos Planos 1–4 (`DataGrid`, `*GridOptions.ts` adapters, `grid-theme.css`, `GRAPHITE_THEME`). TanStack Query continua a fonte. A/B são puros/diretos. C/D exigem integração custom com internals do grid (a API NÃO expõe evento "near-bottom" nem setCell trivial) — a sessão fresh DEVE pesquisar os `.d.ts` indicados antes de codar (não chutar).

**Tech stack:** Next 15/React 19, TS, `@highcharts/grid-pro@3.0.0`, TanStack Query v5, Vitest (só lógica pura é unit-testável; o realtime/scroll é validado por typecheck/build + browser do dono).

---

## Fundação já existente (NÃO recriar) — branch `feat/highcharts-grid-rollout`
- `frontend/src/components/ui/DataGrid.tsx` — wrapper (`{options, className}`; create/update/destroy; dynamic import).
- `frontend/src/lib/grid/gridOptions.ts` — `GRAPHITE_THEME`, `SortDir`, `GridSortState`, `GridCallbacks`, `screenResultsToGridOptions` (screener).
- `frontend/src/lib/grid/fundsGridOptions.ts` — `fundsListToGridOptions`, `escapeHtml`.
- `frontend/src/lib/grid/positionsGridOptions.ts` — `positionsToGridOptions` (cell editing).
- `frontend/src/lib/grid/universeGridOptions.ts` — `universePreviewToGridOptions` (checkbox).
- `frontend/src/lib/grid/grid-theme.css` — tema Graphite + classes de célula.
- Views já migradas: `screener/ResultsTab.tsx`, `funds/FundsView.tsx` (`FundsTable`), `portfolio/PortfolioOverviewView.tsx` (`PositionsTable`), `builder/FundUniverseCard.tsx`.
- `frontend/src/lib/livefeed/useLiveTicks.ts` — `useLiveTicks(symbols: string[]) => { ticks: Record<sym, { price, dir: 1|-1|0, time }>, status }`. rAF-batched (uma re-render por frame). Degrada a no-op sem `NEXT_PUBLIC_LIVEFEED_WS_URL`.

## API do Grid relevante (verificada nos .d.ts; a sessão fresh confirma o resto)
- `Options.rendering.rows`: `{ virtualization?, virtualizationThreshold?, bufferSize?, strictHeights?, minVisibleRows? }`. `lang.noData` NÃO existe nesta versão (por isso empty-state é nosso).
- `Grid.viewport: Table`. `Table`: `tbodyElement` (container de scroll), `rows: TableRow[]` (linhas VISÍVEIS), `getRow(id)`, `getColumn(id)`, `scrollToRow(index)`, `virtualRows`. `RowsVirtualizer.rowCursor` (índice da 1ª linha visível), `buffer`.
- Célula: `Cell.htmlElement`, `Cell.value`, `Row.getCell(id)`. **Não há `setCellValue` público** — atualização ao vivo: ou (i) re-memo das options + `grid.update(options)` (re-render completo, ok para lotes pequenos via rAF), ou (ii) flash direto no DOM via `grid.viewport.getRow(id)?.getCell(colId)?.htmlElement` (a sessão fresh valida qual funciona/é estável).
- Sem evento público "scrolled near bottom" → infinite usa um listener de scroll em `grid.viewport.tbodyElement` (ou `RowsVirtualizer.rowCursor` vs total) para detectar proximidade do fim.

---

## Task A — Empty-state genérico no `DataGrid` (concreto, alta prioridade: corrige regressão dos P1/P2)

**Files:** `frontend/src/lib/grid/gridEmpty.ts` (+ test), `frontend/src/components/ui/DataGrid.tsx`, `screener/ResultsTab.tsx`, `funds/FundsView.tsx`, `portfolio/PortfolioOverviewView.tsx`

- [ ] **A1 — pure helper (TDD):** `gridEmpty.ts` exports `gridRowCount(options: Options): number` = length of the first column array in `options.data?.columns` (0 if none). Test: 0 for empty/absent columns; N for N rows.
- [ ] **A2 — DataGrid:** add prop `emptyMessage?: string`. After the grid renders/updates, if `gridRowCount(options) === 0 && emptyMessage`, show a centered overlay `<div>` (absolutely positioned over the container, Graphite-styled: `text-text-muted text-[13px]`) with the message; else hide it. Keep the container `position: relative`. (The grid still renders its empty body underneath.)
- [ ] **A3 — Wire:** pass `emptyMessage` from each view: screener `ResultsTab` (`total === 0 && search ? \`No matches for "${search}".\` : "No matches — loosen the filters, or the metrics snapshot may not be computed yet."`), funds `FundsView` ("No funds match the current filters."), portfolio (keep its existing `<p>` OR use emptyMessage — pick one, no double message).
- [ ] **A4 — Verify** (lint/typecheck/test) + **commit** `feat(grid): generic empty-state overlay for DataGrid`.

## Task B — Skeleton no formato do grid (concreto)

**Files:** `frontend/src/components/ui/GridSkeleton.tsx`, wire into the views' `isPending` branches.

- [ ] **B1:** create `GridSkeleton({ rows=8, cols=6, className })` — an `animate-pulse` block of fake header + rows (1px-gap bars over `bg-surface-2`, matching the existing skeleton idiom in `StockAnalysisView`/`ResultsTab`). Pure presentational.
- [ ] **B2:** replace the generic `animate-pulse` skeleton in the `isPending` branch of `ResultsTab` and `FundsView` with `<GridSkeleton/>` (keep the surrounding panel/header). Portfolio's overview skeleton can stay or adopt it.
- [ ] **B3:** Verify + commit `feat(grid): grid-shaped loading skeleton`.

## Task C — Infinite-windowed virtual scroll (funds + screener) — RESEARCH then implement

**Files:** the two list views + a small `useInfiniteGrid` hook.

- [ ] **C1 — RESEARCH (read first, do NOT guess):** `…/Grid/Core/Table/Actions/RowsVirtualizer.d.ts`, `…/Grid/Core/Table/Table.d.ts`, and how `DataGrid` could surface the live `Grid` instance (it currently hides it — you may need to add an `onReady?(grid)` or `ref` to `DataGrid`). Confirm: the scroll container element (`grid.viewport.tbodyElement`), how to read scroll position / `rowCursor` vs total, and that appending rows to `data.columns` + `grid.update` keeps scroll position (use `Table.getStateMeta`/`applyStateMeta` if needed).
- [ ] **C2 — Hook:** `useInfiniteGrid` wrapping TanStack `useInfiniteQuery` over the existing paged endpoints (`fetchFunds`/`fetchScreenResults` with `page`/`page_size`), exposing the concatenated rows + `fetchNextPage`/`hasNextPage`. Page size ~100.
- [ ] **C3 — Wire:** feed ALL loaded rows to the adapter→grid (virtualization renders only visible); attach a scroll listener (via the `DataGrid` ready/ref from C1) to `grid.viewport.tbodyElement` that calls `fetchNextPage()` when near the bottom (e.g., `scrollTop + clientHeight >= scrollHeight - threshold`) and `hasNextPage` and not already fetching. Replace the page-button footer with a "loaded X of N" indicator (keep a manual "Load more" fallback button for a11y). Keep server-side sort/filter (changing sort/filter resets the infinite query to page 1).
- [ ] **C4 — Verify** (typecheck/build) + **commit** `feat(grid): infinite-windowed virtual scrolling for funds & screener`. (Interactive scroll → owner browser-validates.)

> Decisão de escopo: manter a paginação por botões como fallback se o infinite se mostrar instável com o `grid.update` (a sessão fresh decide com base no que observar; documentar).

## Task D — Live ticks nas células de preço — RESEARCH then implement

**Files:** the grid(s) with a price column + `useLiveTicks` integration. Natural homes: portfolio `PositionsTable` ("last" column = `last_close`). OPTIONAL bigger win: migrate the **market-overview leaders** table (gainers/losers) to a `DataGrid` and flash it (it already uses `useLiveTicks` today via the hand-rolled table) — only if in scope/time.

- [ ] **D1 — RESEARCH (read first):** confirm the cheapest live-update path — (i) re-memo options + `grid.update` per rAF batch (simplest; fine for the small visible set), vs (ii) targeted DOM flash via `grid.viewport.getRow(id)?.getCell("last")?.htmlElement` (add a `flash-up`/`flash-down` class for a CSS transition, then remove). Pick the stable one. Confirm how `DataGrid` exposes the `Grid` instance (the ready/ref added in C1).
- [ ] **D2 — Integrate:** subscribe `useLiveTicks(visibleTickers)` (the tickers of the rendered rows). On a tick batch, update the "last" cell value + a brief flash class (gain/loss) per `dir`. Show a LIVE/EOD badge near the grid (as `StockAnalysisView` does). Degrade silently when `status !== "live"` (no feed configured).
- [ ] **D3 — CSS:** add `.ix-grid-flash-up`/`.ix-grid-flash-down` (brief bg tint via `--color-gain-muted`/`--color-loss-muted`, transition out) to `grid-theme.css`.
- [ ] **D4 — Verify** (typecheck/build) + **commit** `feat(grid): live price ticks in grid cells (useLiveTicks)`. (Interactive → owner browser-validates with the WS worker configured.)

## Task E — Final verification + handoff
- [ ] `pnpm --dir <worktree>/frontend lint && typecheck && test && build` — all green.
- [ ] Use **superpowers:finishing-a-development-branch** to present integration options for `feat/highcharts-grid-rollout` → `main` (note: `main` advanced to `dbf90f1` with the owner's fixes; the merge brings P2–P5; P1 already on main). The grid foundation lineage may overlap main — verify the merge/rebase cleanly; the owner decides merge vs PR.

## Self-Review (after writing each adapter/helper)
- Pure helpers (`gridRowCount`) unit-tested; components via typecheck/build; realtime/scroll via browser.
- Reuse the foundation; no duplication. Empty-state fixes the documented P1/P2 regression. Keep server-side sort/filter under infinite. Live ticks degrade to no-op without the WS URL.
