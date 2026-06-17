# Highcharts Grid Pro — Universe checkbox-pruning no FundUniverseCard (Plano 4/5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** No modo "universo de fundos" do `/builder/optimize`, mostrar os **top-N fundos ranqueados** num `DataGrid` com **checkboxes (CheckboxRenderer Pro)** para incluir/excluir candidatos específicos antes de otimizar. A poda é enviada ao backend via uma lista explícita de `instrument_id` adicionada ao contrato `UniverseSpecIn`.

**Architecture (full-stack):**
- **Backend (extensão backward-compatible):** `UniverseSpecIn.include_instrument_ids: list[str] | None`. Quando presente, `select_universe_funds` restringe os candidatos a esses ids (mantendo filtros + guardas de NAV/overlap + rank/limit). Quando ausente, comportamento atual (top-N por rank).
- **Frontend:** `FundUniverseCard` busca os top-N fundos (GET /funds com os mesmos filtros + rank, `page_size = effectiveN`) e os renderiza num `DataGrid` com uma coluna de checkbox "Use" (default: todos marcados). A seleção (set de `instrument_id` marcados) é elevada ao `BuilderView`, que injeta `include_instrument_ids` no `OptimizeRequest.universe` ao rodar. O contador existente vira o grid.

**Tech Stack:** FastAPI/SQLAlchemy/Pydantic + pytest (backend); Next 15/React 19/TS + `@highcharts/grid-pro` + TanStack Query + Vitest (frontend). Cadeia de tipos: backend schema → `backend/openapi.json` → `frontend/src/lib/api/api.d.ts` (via `pnpm --dir frontend types`).

**Branch:** `feat/highcharts-grid-rollout`.

---

## Contexto (fatos verificados)
- `UniverseSpecIn` (`backend/app/schemas/builder.py:94`): filtros (fund_type/asset_class/strategy_label/expense_ratio_max/aum_min/sharpe_1y_min/volatility_1y_max/return_1y_min/max_drawdown_1y_min) + `rank_by`/`rank_dir` + `max_assets` (2..MAX_UNIVERSE_ASSETS).
- `OptimizeRequest` (`builder.py:121`): xor `assets`|`universe`; em universe mode `views` é proibido. Validator em `_check_asset_source`.
- `select_universe_funds(session, filters, *, rank_by, rank_dir, max_assets, require_aum=False, window_days, min_obs, today)` (`backend/app/optimizer/data.py:171`): monta `conditions = list(funds_catalog.filter_conditions(filters))`, ordena por `funds_catalog.sort_column(rank_by)`, junta `nav_counts >= min_obs`, `.limit(max_assets)`, retorna `list[UniverseFund]` (id, ticker, name).
- `portfolio_builder.py:212-216` (modo universo): `spec = payload.universe; candidates = await optimizer_data.select_universe_funds(session, <filters>, rank_by=spec.rank_by, rank_dir=spec.rank_dir, max_assets=spec.max_assets, require_aum=needs_bl, ...)`. (Read the exact call before editing.)
- Frontend: `FundUniverseCard` (filter+rank+count, sem lista); `assets.ts` `universeDraftToSpec(draft)` → `BuilderUniverseSpec`, `universeDraftToCountQuery(draft)` (page_size:1). `BuilderView` chama `/builder/optimize`. Funds adapter do Plano 2 (`fundsGridOptions.ts`) e `DataGrid` disponíveis.
- CheckboxRenderer (verificado): `cells.renderer = { type: 'checkbox' }` renderiza um checkbox ligado ao valor booleano da célula; é um `EditModeRenderer`, então alternar dispara `CellEvents.afterEdit (this: TableCell)` com `this.value` = novo booleano.

## File Structure
- **Modify** `backend/app/schemas/builder.py` — add `include_instrument_ids` to `UniverseSpecIn`.
- **Modify** `backend/app/optimizer/data.py` — `select_universe_funds(..., include_ids=None)` aplica `Fund.instrument_id.in_(include_ids)`.
- **Modify** `backend/app/services/portfolio_builder.py` — passar `include_ids=spec.include_instrument_ids` na chamada.
- **Modify** `backend/openapi.json` — regenerar (script existente).
- **Create** `backend/tests/test_optimizer_data.py` cases (ou adicionar) — `select_universe_funds` com `include_ids`.
- **Create**/extend `backend/tests/test_builder_route.py` — universe com `include_instrument_ids`.
- **Modify** `frontend/src/lib/api/api.d.ts` — regenerado (`pnpm types`).
- **Create** `frontend/src/lib/grid/universeGridOptions.ts` (+ test) — adapter do grid de preview com a coluna checkbox.
- **Modify** `frontend/src/components/builder/assets.ts` — `universeDraftToSpec(draft, includeIds?)`.
- **Modify** `frontend/src/components/builder/FundUniverseCard.tsx` — grid de preview + seleção; eleva a seleção.
- **Modify** `frontend/src/components/builder/BuilderView.tsx` — passar a seleção ao request (apenas se podada).

---

## Task 1: Backend — contrato + resolução + testes (TDD pytest)

**Files:** `backend/app/schemas/builder.py`, `backend/app/optimizer/data.py`, `backend/app/services/portfolio_builder.py`, `backend/tests/test_optimizer_data.py`

- [ ] **Step 1 — Test (failing):** Add to `backend/tests/test_optimizer_data.py` a test that, given seeded funds, `select_universe_funds(..., include_ids=[id_a, id_b])` returns ONLY those two (ordered), even when more match the filters. Mirror the existing tests' fixtures/style in that file (READ it first to reuse the session/seed helpers). Run: `cd /e/investintell-light/backend && python -m pytest tests/test_optimizer_data.py -q` → FAIL (unexpected `include_ids` kwarg).

- [ ] **Step 2 — `UniverseSpecIn`:** in `backend/app/schemas/builder.py`, add after `max_assets`:

```python
    include_instrument_ids: (
        Annotated[list[str], Field(min_length=2, max_length=MAX_UNIVERSE_ASSETS)] | None
    ) = None
    """Optional explicit subset (UUID strings) of the ranked universe to keep.

    When the user prunes the previewed top-``max_assets`` candidates via
    checkboxes, the kept ids are sent here; the optimizer runs over exactly
    these (still subject to the same NAV/overlap guards). ``None`` = use the
    full top-``max_assets`` ranked set (default behaviour)."""
```

- [ ] **Step 3 — `select_universe_funds`:** in `backend/app/optimizer/data.py`, add a keyword param `include_ids: Sequence[str] | None = None` (import `Sequence` from `collections.abc` if not present), and inside the conditions block add:

```python
    if include_ids:
        conditions.append(Fund.instrument_id.in_(list(include_ids)))
```

(place it alongside the existing `require_aum` conditions, before building `stmt`).

- [ ] **Step 4 — Wire in `portfolio_builder.py`:** read the `select_universe_funds(...)` call (~line 215) and add `include_ids=spec.include_instrument_ids,` to its kwargs.

- [ ] **Step 5 — Route test:** add to `backend/tests/test_builder_route.py` a case POSTing `/builder/optimize` with `universe.include_instrument_ids = [two seeded fund ids]` and asserting the response weights cover exactly those assets (mirror the existing universe-mode test). Validation: a 1-element list → 422 (Field min_length=2).

- [ ] **Step 6 — Run backend tests + mypy:** `cd /e/investintell-light/backend && python -m pytest tests/test_optimizer_data.py tests/test_builder_route.py -q` (green) and `python -m mypy app` (clean, per project standard). If the venv/activation differs, mirror how the repo runs pytest/mypy (check for a Makefile/justfile/README; do NOT invent a runner).

- [ ] **Step 7 — Regenerate OpenAPI:** regenerate `backend/openapi.json` using the project's existing mechanism (find it: look for `scripts/` dumping `app.openapi()`, a Makefile target, or how the builder commit updated it; e.g. `python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json`). Confirm the new `include_instrument_ids` appears in the `UniverseSpecIn` schema. Commit backend changes:

```bash
cd /e/investintell-light
git add backend/app/schemas/builder.py backend/app/optimizer/data.py backend/app/services/portfolio_builder.py backend/openapi.json backend/tests/test_optimizer_data.py backend/tests/test_builder_route.py
git commit -m "feat(builder): universe optimize accepts include_instrument_ids (checkbox pruning)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend types + preview-grid adapter (TDD adapter)

**Files:** `frontend/src/lib/api/api.d.ts` (regen), `frontend/src/lib/grid/universeGridOptions.ts` (+ test), `frontend/src/components/builder/assets.ts`

- [ ] **Step 1 — Regen types:** `pnpm --dir frontend types` (runs `openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts`). Confirm `BuilderUniverseSpec` now has optional `include_instrument_ids?: string[]` (check `@/lib/api/client`'s `BuilderUniverseSpec` type resolves it). `pnpm --dir frontend typecheck` stays green.

- [ ] **Step 2 — `assets.ts`:** change `universeDraftToSpec` to accept an optional kept-ids set:

```ts
export function universeDraftToSpec(
  draft: UniverseDraft,
  includeIds?: readonly string[],
): BuilderUniverseSpec {
  return {
    ...universeFilters(draft),
    rank_by: draft.rankBy,
    rank_dir: draft.rankDir,
    max_assets: draft.maxAssets,
    ...(includeIds && includeIds.length >= 2 ? { include_instrument_ids: [...includeIds] } : {}),
  };
}
```

(Only send the pruned list when the user actually pruned to a valid subset of ≥2; otherwise full top-N.)

- [ ] **Step 3 — Adapter `universeGridOptions.ts` (TDD):** create `frontend/src/lib/grid/universeGridOptions.test.ts` then `universeGridOptions.ts`. The adapter `universePreviewToGridOptions(funds, selectedIds, callbacks)` builds:
  - data columns: `__include` (boolean = `selectedIds.has(instrument_id)`), `instrument_id` (hidden), plus display fields `ticker`, `name`, `aum_usd`, `expense_ratio`, and the ranked metric columns reused conceptually from the funds renderers.
  - columns: a first `__include` column with `header.format: "Use"`, `cells: { renderer: { type: "checkbox" }, events: { afterEdit(this: TableCell) { const id = this.row.getCell("instrument_id")?.value; callbacks.onToggle(String(id), this.value === true); } } }`; then read-only `ticker` (link, escaped), `name` (truncated), `aum_usd` (`$`+compact), `expense_ratio` (percent), `sharpe_1y`/`return_1y` (number/percent) — reuse the escaping + `numOrDash` patterns from `fundsGridOptions.ts` (import the shared `escapeHtml` from there, or factor a tiny shared util); a hidden `instrument_id` column (`enabled:false`); `rendering.theme = GRAPHITE_THEME`; sorting disabled (the order is the backend rank).

  Tests (pure): `__include` column has `cells.renderer.type === "checkbox"`; data `__include` reflects `selectedIds`; `afterEdit` calls `onToggle(id, checked)` reading `instrument_id` from the row; hidden `instrument_id` column present; ticker link escaped. Use the same mock-`this` (`value`, `row.getCell`, `column.id`) pattern as `fundsGridOptions.test.ts`.

- [ ] **Step 4 — Verify:** `pnpm --dir frontend exec vitest run src/lib/grid/universeGridOptions.test.ts` (green); `pnpm --dir frontend typecheck` (clean).
- [ ] **Step 5 — Commit** `feat(grid): universe preview adapter with include checkbox column` (+ regenerated api.d.ts; + assets.ts).

---

## Task 3: `FundUniverseCard` preview grid + selection; `BuilderView` wiring

**Files:** `frontend/src/components/builder/FundUniverseCard.tsx`, `frontend/src/components/builder/BuilderView.tsx`

- [ ] **Step 1 — Read** both files (BuilderView to see how it owns the `UniverseDraft`, runs optimize, and renders FundUniverseCard; FundUniverseCard for the count query).

- [ ] **Step 2 — Selection state + preview query in `FundUniverseCard`:** keep the existing count query. Add a query for the top-N preview: `fetchFunds({ ...universeFilters(draft via universeDraftToCountQuery but page_size: effectiveN } )` — i.e. same filters + `sort: draft.rankBy, dir: draft.rankDir, page: 1, page_size: effectiveN` (the matching count capped at `maxAssets`). Maintain a `selected: Set<string>` of instrument_ids; when the preview funds load, default-select all of them (an effect that resets selection to all ids when the fund id-set changes). Render the preview via `<DataGrid options={universePreviewToGridOptions(previewFunds, selected, { onToggle })} className="h-[360px] w-full" />` below the existing filter controls. `onToggle(id, checked)` adds/removes from `selected`.

- [ ] **Step 3 — Lift selection:** FundUniverseCard takes a new prop `onSelectionChange: (ids: string[]) => void` (or reuse the existing `onCount` pattern). Report the kept ids up whenever `selected` changes. Distinguish "all selected" (send nothing → full top-N) from "pruned" (send the kept ids): only report a pruned list when `selected.size < previewFunds.length && selected.size >= 2`.

- [ ] **Step 4 — Wire `BuilderView`:** hold the kept-ids in BuilderView state (set via FundUniverseCard's `onSelectionChange`); when building the universe-mode `OptimizeRequest`, call `universeDraftToSpec(draft, keptIds)` so `include_instrument_ids` is sent only when pruned. Keep the run gate (≥2 funds) consistent with the pruned count.

- [ ] **Step 5 — Verify:** `pnpm --dir frontend lint`, `pnpm --dir frontend typecheck`, `pnpm --dir frontend test` (all green).
- [ ] **Step 6 — Commit** `feat(builder): preview top-N funds in a grid with include checkboxes (universe pruning)`.

---

## Task 4: Verificação integrada (build)
- [ ] `pnpm --dir frontend build` (`/builder` compila). Browser (owner): preview grid mostra os top-N; desmarcar reduz o set; rodar otimiza só os marcados (Network: `universe.include_instrument_ids`); marcar todos volta ao top-N; tema/dark-light.

## Self-Review
- Spec coverage: backend contract + resolução + pytest (T1), tipos+adapter checkbox (T2), preview grid + seleção + wiring (T3), build (T4). ✓
- Placeholders: backend code verbatim; frontend Task 3 é integração (precisa ler BuilderView/FundUniverseCard) — instruções precisas, validadas por typecheck/build/browser (a edição via checkbox é interativa, não unit-testável). O adapter (T2) é puro e testado.
- Type/contract consistency: `include_instrument_ids` (backend schema) ↔ `BuilderUniverseSpec.include_instrument_ids?` (regen) ↔ `universeDraftToSpec(draft, includeIds)` ↔ `select_universe_funds(..., include_ids)`. Reusa `GRAPHITE_THEME`/`DataGrid`/escaping do Plano 2.
- **Caveat full-stack:** a cadeia de regen (schema→openapi.json→api.d.ts) deve rodar na ordem; o implementer confirma o mecanismo de dump do openapi do projeto (não inventar).
