# Screener Unified Redesign (Plano 6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the screener's 3-tab wizard (Select metrics / Build / Results) with a unified workspace — a persistent header + a single **Build** tab (typeahead "Add a metric" + editable Highcharts Grid Pro filters list + bottom distribution panel) + the existing **Results** tab.

**Architecture:** Auto-save persistence is preserved (every bound/selection PUT/DELETE persists and `applyFilterResponse` folds the response into the TanStack Query cache). Two new backend endpoints land: `PATCH /screener/screens/{id}/filters/reorder` (drag handle → column order) and `GET /screener/screens/{id}/build` (one request feeds every filter's sparkline + the active-row distribution panel). The filters list becomes a second Grid Pro surface (a new pure adapter `filtersGridOptions.ts` mirroring the existing `gridOptions.ts`). `SelectMetricsTab` + `BuildTab` are merged into `BuildPanel`; `ScreenStrip` becomes the header's `ScreenSwitcher`; `ResultsTab` keeps its server-driven grid but its title row moves up into the shared header.

**Tech Stack:** Backend FastAPI + SQLAlchemy async (pytest). Frontend Next.js 15 / React 19, TanStack Query v5, Highcharts Grid Pro 3.0.0, ECharts 6, Tailwind 4 (Graphite/Cockpit tokens), vitest. Spec: `docs/superpowers/specs/2026-06-13-screener-unified-redesign-design.md`.

**Working branch:** `feat/screener-redesign` (worktree at `.claude/worktrees/screener-redesign`, base `main`). Baseline green: 18 vitest tests, `tsc --noEmit` clean.

---

## File Structure

**Backend (create/modify):**
- Modify `backend/app/schemas/screener.py` — add `FilterReorder`, `MetricBuildOut`, `BuildAllResponse`.
- Modify `backend/app/services/screener.py` — add `reorder_filters()`.
- Modify `backend/app/api/routes/screener.py` — add `PATCH .../filters/reorder` and `GET .../build` routes.
- Test `backend/tests/test_screener_routes.py` — reorder + build-all route tests.
- Test `backend/tests/test_screener_service.py` — `reorder_filters` service test (create if absent; otherwise append).
- Regenerate `backend/openapi.json` (FastAPI export script) → `frontend/src/lib/api/api.d.ts`.

**Frontend — pure logic (create):**
- `frontend/src/lib/screener/bounds.ts` — shared percent display/parse helpers (extracted from `BuildTab`).
- `frontend/src/lib/screener/bounds.test.ts`
- `frontend/src/lib/grid/filtersGridOptions.ts` — `ScreenFilter[]` + distributions → Grid Pro `Options` (editable).
- `frontend/src/lib/grid/filtersGridOptions.test.ts`
- `frontend/src/lib/grid/sparkline.ts` — `Distribution` + bounds → inline SVG bar string.
- `frontend/src/lib/grid/sparkline.test.ts`

**Frontend — API client (modify):**
- `frontend/src/lib/api/client.ts` — add `reorderScreenFilters()`, `fetchScreenBuildAll()`, export `BuildAll`/`FilterReorderBody` types.

**Frontend — components (create):**
- `frontend/src/components/screener/BuildPanel.tsx` — merges Select Metrics + Build.
- `frontend/src/components/screener/AddMetricBar.tsx` — typeahead + Browse trigger.
- `frontend/src/components/screener/MetricBrowserPopover.tsx` — categorized catalog, checkbox add.
- `frontend/src/components/screener/FiltersGrid.tsx` — `DataGrid` + `filtersGridOptions` + mutations.
- `frontend/src/components/screener/DistributionPanel.tsx` — ECharts histogram + presets + bounds (active row).
- `frontend/src/components/screener/ScreenerHeader.tsx` — `ScreenSwitcher` + match count + save status + Reset/Export.

**Frontend — components (modify):**
- `frontend/src/components/screener/ScreenerView.tsx` — header + 2 tabs (`?tab=build|results`); remove `WizardTabs`/`ScreenWizardBody`/old `EmptyState`.
- `frontend/src/components/screener/ResultsTab.tsx` — drop the local title row (count/export move to header); keep search + pagination + grid.
- `frontend/src/components/screener/shared.tsx` — no change expected; reuse existing classes.

**Frontend — components (delete, after merge):**
- `frontend/src/components/screener/SelectMetricsTab.tsx`
- `frontend/src/components/screener/BuildTab.tsx`

---

## FASE A — Backend (new endpoints + types)

### Task 1: Reorder endpoint (`PATCH /screener/screens/{id}/filters/reorder`)

**Files:**
- Modify: `backend/app/schemas/screener.py`
- Modify: `backend/app/services/screener.py`
- Modify: `backend/app/api/routes/screener.py`
- Test: `backend/tests/test_screener_routes.py`

- [ ] **Step 1: Write the failing route test**

In `backend/tests/test_screener_routes.py` (follow the existing fixtures/style in that file), add:

```python
@pytest.mark.anyio
async def test_reorder_filters_rewrites_position_order(client, seeded_screen):
    # seeded_screen has filters added in order: pe_ratio (0), market_cap (1), roe (2)
    sid = seeded_screen["id"]
    resp = await client.patch(
        f"/screener/screens/{sid}/filters/reorder",
        json={"metric_codes": ["roe", "pe_ratio", "market_cap"]},
    )
    assert resp.status_code == 200
    codes = [f["metric_code"] for f in resp.json()["filters"]]
    assert codes == ["roe", "pe_ratio", "market_cap"]
    positions = [f["position"] for f in resp.json()["filters"]]
    assert positions == [0, 1, 2]


@pytest.mark.anyio
async def test_reorder_filters_rejects_mismatched_set(client, seeded_screen):
    sid = seeded_screen["id"]
    resp = await client.patch(
        f"/screener/screens/{sid}/filters/reorder",
        json={"metric_codes": ["roe", "pe_ratio"]},  # missing market_cap
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_reorder_filters_unknown_screen_404(client):
    resp = await client.patch(
        "/screener/screens/999999/filters/reorder", json={"metric_codes": []}
    )
    assert resp.status_code == 404
```

If `seeded_screen` does not exist as a fixture, create it near the other fixtures: a screen with three filters (`pe_ratio`, `market_cap`, `roe`) added via the service `upsert_filter`, returned as the GET `/screens/{id}` JSON.

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd backend && pytest tests/test_screener_routes.py -k reorder -v`
Expected: FAIL (404 route not found / `seeded_screen` missing).

- [ ] **Step 3: Add the `FilterReorder` schema**

In `backend/app/schemas/screener.py`, after `FilterBody`:

```python
class FilterReorder(BaseModel):
    """Body for PATCH /screener/screens/{id}/filters/reorder.

    Must list EXACTLY the screen's current filter codes, in the desired order.
    """

    metric_codes: list[str] = Field(
        description="All of the screen's current filter metric codes, in the new order."
    )
```

- [ ] **Step 4: Add the `reorder_filters` service**

In `backend/app/services/screener.py`, add `update` to the sqlalchemy import line, then after `delete_filter`:

```python
async def reorder_filters(
    session: AsyncSession, screen_id: int, metric_codes: Sequence[str]
) -> None:
    """Rewrite filter positions to match metric_codes order (0-based).

    The route has validated the screen exists and that metric_codes is exactly
    the set of the screen's current filter codes (no missing/extra/duplicate).
    position has no UNIQUE constraint, so a plain per-row UPDATE is safe.
    """
    for position, code in enumerate(metric_codes):
        await session.execute(
            update(ScreenFilter)
            .where(
                ScreenFilter.screen_id == screen_id,
                ScreenFilter.metric_code == code,
            )
            .values(position=position)
        )
    await session.commit()
```

- [ ] **Step 5: Add the route**

In `backend/app/api/routes/screener.py`, import `FilterReorder` from schemas, then after `delete_filter`:

```python
@router.patch("/screens/{screen_id}/filters/reorder", response_model=ScreenOut)
async def reorder_filters(
    screen_id: int, payload: FilterReorder, session: SessionDep
) -> ScreenOut:
    """Reorder a screen's filters; position drives the Results column order."""
    screen = await _screen_or_404(session, screen_id)
    requested = list(payload.metric_codes)
    existing = {f.metric_code for f in screen.filters}
    if len(requested) != len(set(requested)):
        raise HTTPException(status_code=422, detail="Duplicate metric codes in reorder payload.")
    if set(requested) != existing:
        raise HTTPException(
            status_code=422,
            detail="Reorder payload must list exactly the screen's current filter codes.",
        )
    await screener_service.reorder_filters(session, screen_id, requested)
    return ScreenOut.model_validate(await _screen_or_404(session, screen_id))
```

- [ ] **Step 6: Run the test, verify it passes**

Run: `cd backend && pytest tests/test_screener_routes.py -k reorder -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/screener.py backend/app/services/screener.py backend/app/api/routes/screener.py backend/tests/test_screener_routes.py
git commit -m "feat(screener): PATCH filters/reorder endpoint (column order)"
```

### Task 2: Batch build endpoint (`GET /screener/screens/{id}/build`)

**Files:**
- Modify: `backend/app/schemas/screener.py`
- Modify: `backend/app/api/routes/screener.py`
- Test: `backend/tests/test_screener_routes.py`

- [ ] **Step 1: Write the failing route test**

```python
@pytest.mark.anyio
async def test_build_all_returns_every_filter(client, seeded_screen):
    sid = seeded_screen["id"]
    resp = await client.get(f"/screener/screens/{sid}/build")
    assert resp.status_code == 200
    body = resp.json()
    assert "headline_count" in body
    codes = [m["metric_code"] for m in body["metrics"]]
    assert codes == ["pe_ratio", "market_cap", "roe"]  # position order
    for m in body["metrics"]:
        assert "available_count" in m
        assert "distribution" in m  # may be null when snapshot empty


@pytest.mark.anyio
async def test_build_all_empty_screen_has_no_metrics(client):
    create = await client.post("/screener/screens", json={"name": "empty-build"})
    sid = create.json()["id"]
    resp = await client.get(f"/screener/screens/{sid}/build")
    assert resp.status_code == 200
    assert resp.json()["metrics"] == []
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd backend && pytest tests/test_screener_routes.py -k build_all -v`
Expected: FAIL (404 route not found).

- [ ] **Step 3: Add the batch schemas**

In `backend/app/schemas/screener.py`, after `BuildResponse`:

```python
class MetricBuildOut(BaseModel):
    """One filter's distribution + availability for the batch build payload."""

    metric_code: str
    distribution: DistributionOut | None
    available_count: int


class BuildAllResponse(BaseModel):
    """GET /screener/screens/{id}/build — every filter's distribution in one round-trip.

    headline_count honors ALL filters (the live match count); each metric's
    distribution is the universe-wide histogram (null when the snapshot has no
    data for it), feeding the per-row sparklines and the active-row panel.
    """

    headline_count: int
    metrics: list[MetricBuildOut]
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes/screener.py`, import `BuildAllResponse, MetricBuildOut`, then after `build_metric`:

```python
@router.get("/screens/{screen_id}/build", response_model=BuildAllResponse)
async def build_all(screen_id: int, session: SessionDep) -> BuildAllResponse:
    """Every filter's universe distribution + the live headline count, one round-trip."""
    screen = await _screen_or_404(session, screen_id)
    headline_count = await screener_service.count_matching(session, screen.filters)
    metrics: list[MetricBuildOut] = []
    for item in sorted(screen.filters, key=lambda f: f.position):
        metric = _metric_or_422(item.metric_code)
        available = await screener_service.count_metric_available(session, metric.code)
        try:
            distribution = DistributionOut.model_validate(
                await screener_service.compute_distribution(session, metric)
            )
        except screener_service.MetricDataUnavailableError:
            distribution = None
        metrics.append(
            MetricBuildOut(
                metric_code=metric.code, distribution=distribution, available_count=available
            )
        )
    return BuildAllResponse(headline_count=headline_count, metrics=metrics)
```

- [ ] **Step 5: Run the test, verify it passes**

Run: `cd backend && pytest tests/test_screener_routes.py -k build_all -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full backend suite (no regressions)**

Run: `cd backend && pytest -q`
Expected: PASS (existing count + 5 new).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/screener.py backend/app/api/routes/screener.py backend/tests/test_screener_routes.py
git commit -m "feat(screener): GET /build batch endpoint (all filter distributions)"
```

### Task 3: Regenerate types + API client functions

**Files:**
- Regenerate: `backend/openapi.json`, `frontend/src/lib/api/api.d.ts`
- Modify: `frontend/src/lib/api/client.ts`

- [ ] **Step 1: Export OpenAPI + regenerate the TS types**

Run (from repo root; the export command is the one the project already uses — check `backend/README` or the existing `openapi.json` provenance, typically `python -m app.export_openapi` or a script):

```bash
cd backend && python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi()))"
cd ../frontend && npm run types
```
Expected: `git diff` shows the two new paths (`.../filters/reorder`, `.../build`) and `BuildAllResponse`/`MetricBuildOut`/`FilterReorder` schemas in `api.d.ts`.

- [ ] **Step 2: Add client functions + types**

In `frontend/src/lib/api/client.ts`, alongside the other screener exports (`putScreenFilter`, `fetchBuildMetric`, …):

```typescript
export type BuildAll =
  ScreenBuildAllOperation["responses"]["200"]["content"]["application/json"];
export type MetricBuild = BuildAll["metrics"][number];
export type FilterReorderBody =
  ScreenFiltersReorderPath["patch"]["requestBody"]["content"]["application/json"];

export async function fetchScreenBuildAll(
  screenId: number,
  signal?: AbortSignal,
): Promise<BuildAll> {
  return request<BuildAll>(`/screener/screens/${screenId}/build`, { signal });
}

export async function reorderScreenFilters(
  screenId: number,
  metricCodes: string[],
): Promise<Screen> {
  return request<Screen>(`/screener/screens/${screenId}/filters/reorder`, {
    method: "PATCH",
    body: JSON.stringify({ metric_codes: metricCodes } satisfies FilterReorderBody),
  });
}
```

Note: match the operation/path type aliases to whatever `openapi-typescript` names them (inspect `api.d.ts` after Step 1 — the existing aliases like `ScreenBuildOperation`, `ScreenFilterPath` show the naming pattern). Reuse the existing `request()` helper (same one `putScreenFilter` uses).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no errors).

- [ ] **Step 4: Commit**

```bash
git add backend/openapi.json frontend/src/lib/api/api.d.ts frontend/src/lib/api/client.ts
git commit -m "feat(screener): regen types + reorder/build-all client functions"
```

---

## FASE B — Frontend pure logic (unit-tested, no React)

### Task 4: Shared bound helpers (`lib/screener/bounds.ts`)

DRY: the percent display/parse rule currently lives inline in `BuildTab.tsx`. Extract it so the
editable grid and the distribution panel share ONE implementation.

**Files:**
- Create: `frontend/src/lib/screener/bounds.ts`
- Test: `frontend/src/lib/screener/bounds.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/screener/bounds.test.ts
import { describe, it, expect } from "vitest";
import { toDisplayText, parseBound } from "./bounds";

describe("toDisplayText", () => {
  it("renders null as an empty string", () => expect(toDisplayText(null, false)).toBe(""));
  it("scales percent fractions to 0-100", () => expect(toDisplayText(0.05, true)).toBe("5"));
  it("passes non-percent values through", () => expect(toDisplayText(25, false)).toBe("25"));
});

describe("parseBound", () => {
  it("treats blank as unbounded (null)", () => expect(parseBound("  ", false)).toBeNull());
  it("returns undefined for invalid input", () => expect(parseBound("abc", false)).toBeUndefined());
  it("converts percent input to a fraction", () => expect(parseBound("5", true)).toBe(0.05));
  it("keeps raw values for non-percent", () => expect(parseBound("25", false)).toBe(25));
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && npx vitest run src/lib/screener/bounds.test.ts`
Expected: FAIL ("Failed to resolve import ./bounds").

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/screener/bounds.ts
import { parseDecimal } from "@/lib/parse";

/** API value -> input text. Percent fractions display as 0-100. */
export function toDisplayText(value: number | null, isPercent: boolean): string {
  if (value === null) return "";
  return String(isPercent ? value * 100 : value);
}

/** Input text -> API value: "" = unbounded (null); invalid = undefined (no commit). */
export function parseBound(text: string, isPercent: boolean): number | null | undefined {
  if (text.trim() === "") return null;
  const v = parseDecimal(text);
  if (!Number.isFinite(v)) return undefined;
  return isPercent ? v / 100 : v;
}
```

- [ ] **Step 4: Run it, verify it passes**

Run: `cd frontend && npx vitest run src/lib/screener/bounds.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/screener/bounds.ts frontend/src/lib/screener/bounds.test.ts
git commit -m "feat(screener): extract shared percent bound helpers"
```

### Task 5: Distribution sparkline (`lib/grid/sparkline.ts` + theme CSS)

**Files:**
- Create: `frontend/src/lib/grid/sparkline.ts`
- Test: `frontend/src/lib/grid/sparkline.test.ts`
- Modify: `frontend/src/lib/grid/grid-theme.css`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/grid/sparkline.test.ts
import { describe, it, expect } from "vitest";
import { sparklineSvg } from "./sparkline";

const dist = { bin_edges: [0, 10, 20, 30], counts: [1, 4, 2], counts_normalized: [0.25, 1, 0.5] };

describe("sparklineSvg", () => {
  it("renders one rect per bin", () => {
    const svg = sparklineSvg(dist, { min: null, max: null });
    expect((svg.match(/<rect/g) ?? []).length).toBe(3);
  });
  it("marks bins overlapping the [min,max] band as selected", () => {
    const svg = sparklineSvg(dist, { min: null, max: 15 }); // [0,10) and [10,20) overlap
    expect((svg.match(/ix-spark-on/g) ?? []).length).toBe(2);
  });
  it("returns an empty string for an empty distribution", () => {
    expect(sparklineSvg({ bin_edges: [], counts: [], counts_normalized: [] }, { min: null, max: null })).toBe("");
  });
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && npx vitest run src/lib/grid/sparkline.test.ts`
Expected: FAIL (import unresolved).

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/grid/sparkline.ts
import type { Distribution } from "@/lib/api/client";

/** Inline SVG mini-histogram. Bars overlapping [min,max] get the accent class. */
export function sparklineSvg(
  dist: Pick<Distribution, "bin_edges" | "counts_normalized">,
  bounds: { min: number | null; max: number | null },
  opts: { width?: number; height?: number } = {},
): string {
  const width = opts.width ?? 64;
  const height = opts.height ?? 16;
  const n = dist.counts_normalized.length;
  if (n === 0) return "";
  const gap = 1;
  const barW = (width - gap * (n - 1)) / n;
  const bars = dist.counts_normalized
    .map((norm, i) => {
      const h = Math.max(1, Math.round(norm * (height - 1)));
      const x = i * (barW + gap);
      const lo = dist.bin_edges[i];
      const hi = dist.bin_edges[i + 1];
      const inBand =
        (bounds.min === null || hi > bounds.min) && (bounds.max === null || lo < bounds.max);
      const cls = inBand ? "ix-spark-bar ix-spark-on" : "ix-spark-bar";
      return `<rect class="${cls}" x="${x.toFixed(2)}" y="${height - h}" width="${barW.toFixed(2)}" height="${h}"/>`;
    })
    .join("");
  return `<svg class="ix-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${bars}</svg>`;
}
```

- [ ] **Step 4: Run it, verify it passes**

Run: `cd frontend && npx vitest run src/lib/grid/sparkline.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the theme classes**

Append to `frontend/src/lib/grid/grid-theme.css`:

```css
/* Distribution sparkline (filters grid cell). */
.hcg-theme-graphite .ix-spark { display: inline-block; vertical-align: middle; }
.hcg-theme-graphite .ix-spark-bar { fill: var(--color-chart-bar-mute); }
.hcg-theme-graphite .ix-spark-on { fill: var(--color-accent); }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/grid/sparkline.ts frontend/src/lib/grid/sparkline.test.ts frontend/src/lib/grid/grid-theme.css
git commit -m "feat(screener): distribution sparkline SVG + theme classes"
```

### Task 6: Editable filters adapter (`lib/grid/filtersGridOptions.ts`)

Mirrors `gridOptions.ts`/`positionsGridOptions.ts`/`universeGridOptions.ts` (the established Grid Pro
patterns: `editMode` cells, `renderer: { type: "checkbox" }`, `events.afterEdit`/`events.click`,
hidden `enabled:false` columns). The grid's row order is the filter `position`; sorting is disabled
(reorder is explicit via ↑/↓). Min/Max are editable; the Dist column shows a pre-rendered sparkline.

> **Reorder note:** ↑/↓ columns (two narrow columns, each with its own `events.click`) are used
> instead of a draggable `☰` handle — the Grid Pro adapters in this repo expose no native row-drag,
> and ↑/↓ is deterministic + keyboard-accessible. `onMove` recomputes the code order; the component
> calls `reorderScreenFilters`.

**Files:**
- Create: `frontend/src/lib/grid/filtersGridOptions.ts`
- Test: `frontend/src/lib/grid/filtersGridOptions.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/grid/filtersGridOptions.test.ts
import { describe, it, expect } from "vitest";
import { screenFiltersToGridOptions, filtersGridData } from "./filtersGridOptions";
import type { MetricDef, ScreenFilter, MetricBuild } from "@/lib/api/client";

const PE: MetricDef = {
  code: "pe_ratio", name: "Price / Earnings (TTM)", abbreviation: "P/E",
  category: "Fundamentals: Valuation", sub_category: "Multiples", data_type: "float",
  scale_note: "", presets: [],
};
const ROE: MetricDef = { ...PE, code: "roe", name: "Return on Equity", abbreviation: "ROE", data_type: "percent" };
const catalog = new Map<string, MetricDef>([["pe_ratio", PE], ["roe", ROE]]);
const filters: ScreenFilter[] = [
  { metric_code: "pe_ratio", min_value: null, max_value: 25, position: 0 },
  { metric_code: "roe", min_value: 0.15, max_value: null, position: 1 },
];
const builds = new Map<string, MetricBuild>([
  ["pe_ratio", { metric_code: "pe_ratio", available_count: 100, distribution: { bin_edges: [0, 12, 25], counts: [3, 1], counts_normalized: [1, 0.3] } }],
  ["roe", { metric_code: "roe", available_count: 100, distribution: null }],
]);

const noop = { onEditBound() {}, onRemove() {}, onMove() {}, onToggleSelect() {}, onSelectRow() {} };

describe("filtersGridData", () => {
  it("scales percent bounds to 0-100 for display", () => {
    const data = filtersGridData(filters, catalog, builds, new Set());
    // roe is the 2nd row; min_value 0.15 -> 15 (percent display)
    expect(data.columns.min[1]).toBe(15);
    expect(data.columns.max[0]).toBe(25); // pe_ratio raw
  });
  it("marks selected rows in the __select column", () => {
    const data = filtersGridData(filters, catalog, builds, new Set(["roe"]));
    expect(data.columns.__select).toEqual([false, true]);
  });
});

describe("screenFiltersToGridOptions", () => {
  it("emits a column per control + hidden metric_code", () => {
    const opts = screenFiltersToGridOptions(filters, catalog, builds, new Set(), noop);
    const ids = (opts.columns ?? []).map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining(["__select", "__up", "__down", "metric", "min", "max", "dist", "__remove", "metric_code"]),
    );
  });
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && npx vitest run src/lib/grid/filtersGridOptions.test.ts`
Expected: FAIL (import unresolved).

- [ ] **Step 3: Implement the adapter**

```typescript
// frontend/src/lib/grid/filtersGridOptions.ts
import type { Options, TableCell } from "@highcharts/grid-pro";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { formatMetricValue } from "@/lib/format";
import { sparklineSvg } from "./sparkline";
import { escapeHtml } from "./fundsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export interface FiltersGridCallbacks {
  /** A Min/Max cell was edited; `value` is the API value (fraction for percent) or null (unbounded). */
  onEditBound: (metricCode: string, which: "min" | "max", value: number | null) => void;
  onRemove: (metricCode: string) => void;
  onMove: (metricCode: string, direction: "up" | "down") => void;
  onToggleSelect: (metricCode: string, checked: boolean) => void;
  /** Row activated (Metric cell clicked) → drives the DistributionPanel. */
  onSelectRow: (metricCode: string) => void;
}

const isPercent = (m: MetricDef | undefined): boolean => m?.data_type === "percent";
const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

/** API bound -> display number (percent fractions shown as 0-100). */
function toDisplay(value: number | null, percent: boolean): number | null {
  return value === null ? null : percent ? value * 100 : value;
}

/* ── formatters ───────────────────────────────────────────────────── */
function metricFormatter(this: GridCell): string {
  const abbr = this.row.getCell("abbr")?.value;
  const sub = abbr ? `<span class="ix-grid-sub">${escapeHtml(abbr)}</span>` : "";
  return `<button type="button" class="ix-grid-rowname">${escapeHtml(this.value ?? "")}</button>${sub}`;
}
function boundFormatter(this: GridCell): string {
  if (this.value === null || this.value === "") return `<span class="ix-grid-editable">—</span>`;
  const unit = this.row.getCell("unit")?.value;
  return `<span class="ix-grid-editable">${escapeHtml(String(this.value))}${unit ? escapeHtml(String(unit)) : ""}</span>`;
}
function distFormatter(this: GridCell): string {
  return this.value ? String(this.value) : "—"; // pre-rendered SVG string (or em-dash)
}
function upFormatter(this: GridCell): string {
  return `<span class="ix-grid-mv" title="Move up" aria-label="Move up">↑</span>`;
}
function downFormatter(this: GridCell): string {
  return `<span class="ix-grid-mv" title="Move down" aria-label="Move down">↓</span>`;
}
function removeFormatter(this: GridCell): string {
  return `<span class="ix-grid-remove" title="Remove" aria-label="Remove filter">×</span>`;
}

const codeOf = (cell: TableCell): string | null => {
  const code = cell.row.getCell("metric_code")?.value;
  return code == null ? null : String(code);
};

/* ── columns ──────────────────────────────────────────────────────── */
export function filtersGridColumns(callbacks: FiltersGridCallbacks): GridColumns {
  return [
    {
      id: "__select", header: { format: "" }, className: "ix-grid-cell-check",
      cells: {
        renderer: { type: "checkbox" },
        events: { afterEdit(this: TableCell) { const c = codeOf(this); if (c) callbacks.onToggleSelect(c, this.value === true); } },
      },
    },
    {
      id: "__up", header: { format: "" }, className: "ix-grid-cell-mv",
      cells: { formatter: upFormatter, events: { click(this: TableCell) { const c = codeOf(this); if (c) callbacks.onMove(c, "up"); } } },
    },
    {
      id: "__down", header: { format: "" }, className: "ix-grid-cell-mv",
      cells: { formatter: downFormatter, events: { click(this: TableCell) { const c = codeOf(this); if (c) callbacks.onMove(c, "down"); } } },
    },
    {
      id: "metric", header: { format: "Metric" }, className: "ix-grid-cell-text",
      cells: { formatter: metricFormatter, events: { click(this: TableCell) { const c = codeOf(this); if (c) callbacks.onSelectRow(c); } } },
    },
    { id: "min", header: { format: "Min" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: boundFormatter, editMode: { enabled: true } } },
    { id: "max", header: { format: "Max" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: boundFormatter, editMode: { enabled: true } } },
    { id: "dist", header: { format: "Distribution" }, className: "ix-grid-cell-num", cells: { formatter: distFormatter } },
    {
      id: "__remove", header: { format: "" }, className: "ix-grid-cell-num",
      cells: { formatter: removeFormatter, events: { click(this: TableCell) { const c = codeOf(this); if (c) callbacks.onRemove(c); } } },
    },
    // hidden data-only columns used by formatters / handlers via row.getCell
    { id: "metric_code", enabled: false },
    { id: "abbr", enabled: false },
    { id: "unit", enabled: false },
    { id: "is_percent", enabled: false },
  ];
}

/* ── data ─────────────────────────────────────────────────────────── */
export function filtersGridData(
  filters: ScreenFilter[],
  catalog: Map<string, MetricDef>,
  builds: Map<string, MetricBuild>,
  selected: ReadonlySet<string>,
): LocalGridData {
  const ordered = [...filters].sort((a, b) => a.position - b.position);
  const columns: Record<string, Array<string | number | boolean | null>> = {
    __select: ordered.map((f) => selected.has(f.metric_code)),
    __up: ordered.map(() => null),
    __down: ordered.map(() => null),
    metric: ordered.map((f) => catalog.get(f.metric_code)?.name ?? f.metric_code),
    metric_code: ordered.map((f) => f.metric_code),
    abbr: ordered.map((f) => catalog.get(f.metric_code)?.abbreviation ?? ""),
    unit: ordered.map((f) => (isPercent(catalog.get(f.metric_code)) ? "%" : "")),
    is_percent: ordered.map((f) => isPercent(catalog.get(f.metric_code))),
    min: ordered.map((f) => toDisplay(f.min_value, isPercent(catalog.get(f.metric_code)))),
    max: ordered.map((f) => toDisplay(f.max_value, isPercent(catalog.get(f.metric_code)))),
    dist: ordered.map((f) => {
      const d = builds.get(f.metric_code)?.distribution;
      return d ? sparklineSvg(d, { min: f.min_value, max: f.max_value }) : null;
    }),
  };
  return { providerType: "local", columns };
}

/* ── full options ─────────────────────────────────────────────────── */
export function screenFiltersToGridOptions(
  filters: ScreenFilter[],
  catalog: Map<string, MetricDef>,
  builds: Map<string, MetricBuild>,
  selected: ReadonlySet<string>,
  callbacks: FiltersGridCallbacks,
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: false, strictHeights: true } },
    columnDefaults: {
      sorting: { enabled: false },
      cells: {
        events: {
          afterEdit(this: TableCell) {
            const colId = this.column?.id;
            if (colId !== "min" && colId !== "max") return;
            const code = codeOf(this);
            if (!code) return;
            const percent = this.row.getCell("is_percent")?.value === true;
            const display = num(this.value);
            const apiValue = display === null ? null : percent ? display / 100 : display;
            callbacks.onEditBound(code, colId, apiValue);
          },
        },
      },
    },
    columns: filtersGridColumns(callbacks),
    data: filtersGridData(filters, catalog, builds, selected),
  };
}
```

- [ ] **Step 4: Run it, verify it passes**

Run: `cd frontend && npx vitest run src/lib/grid/filtersGridOptions.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the move/rowname theme classes**

Append to `frontend/src/lib/grid/grid-theme.css`:

```css
/* Filters grid: row controls. */
.hcg-theme-graphite .ix-grid-cell-mv { width: 26px; text-align: center; }
.hcg-theme-graphite .ix-grid-mv { cursor: pointer; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-mv:hover { color: var(--color-accent); }
.hcg-theme-graphite .ix-grid-rowname { background: none; border: 0; padding: 0; color: var(--color-text-primary); font: inherit; cursor: pointer; }
.hcg-theme-graphite .ix-grid-rowname:hover { color: var(--color-accent); }
.hcg-theme-graphite .ix-grid-sub { color: var(--color-text-muted); font-size: 11px; margin-left: 6px; }
.hcg-theme-graphite .ix-grid-editable { border-bottom: 1px dashed var(--color-border-strong); }
.hcg-theme-graphite .ix-grid-remove { cursor: pointer; color: var(--color-text-muted); }
.hcg-theme-graphite .ix-grid-remove:hover { color: var(--color-loss); }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/grid/filtersGridOptions.ts frontend/src/lib/grid/filtersGridOptions.test.ts frontend/src/lib/grid/grid-theme.css
git commit -m "feat(screener): editable filters Grid Pro adapter (min/max, select, move, sparkline)"
```

---

## FASE C — Frontend components

> Components are **controlled** — all persistence (PUT/DELETE/reorder) is owned by `BuildPanel`
> (Task 11) and passed down as callbacks, so the leaf components stay pure-ish and testable. JSX
> uses the existing Graphite tokens and the shared classes from `shared.tsx`
> (`INPUT_CLASS`, `BUTTON_CLASS`, `BUTTON_PRIMARY_CLASS`, `FIELD_LABEL_CLASS`).

### Task 7: `DistributionPanel.tsx` (active-row distribution, width-controlled)

Reuses the existing `buildDistributionOption` + `EChart` + `chartColors` (the same pieces `BuildTab`
uses today). Shows the active filter's histogram in a `max-w-[560px]` block, preset chips, Min/Max
inputs, and Move ↑/↓ — all controlled via callbacks.

**Files:**
- Create: `frontend/src/components/screener/DistributionPanel.tsx`

- [ ] **Step 1: Implement the component**

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { EChart } from "@/components/charts/EChart";
import { FIELD_LABEL_CLASS } from "@/components/screener/shared";
import { buildDistributionOption } from "@/lib/charts/distribution";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatCompact } from "@/lib/format";
import { parseBound, toDisplayText } from "@/lib/screener/bounds";

export function DistributionPanel({
  metric,
  filter,
  build,
  headline,
  canMoveUp,
  canMoveDown,
  onEditBound,
  onApplyPreset,
  onMove,
}: {
  metric: MetricDef;
  filter: ScreenFilter;
  build: MetricBuild | undefined;
  headline: number | null;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onEditBound: (which: "min" | "max", value: number | null) => void;
  onApplyPreset: (min: number | null, max: number | null) => void;
  onMove: (direction: "up" | "down") => void;
}) {
  const isPercent = metric.data_type === "percent";
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => setColors(chartColors()), []);

  const [minText, setMinText] = useState(() => toDisplayText(filter.min_value, isPercent));
  const [maxText, setMaxText] = useState(() => toDisplayText(filter.max_value, isPercent));
  // Re-sync when the active row OR its persisted bounds change (edited via grid).
  useEffect(() => {
    setMinText(toDisplayText(filter.min_value, isPercent));
    setMaxText(toDisplayText(filter.max_value, isPercent));
  }, [filter.metric_code, filter.min_value, filter.max_value, isPercent]);

  const dist = build?.distribution ?? null;
  const option = useMemo(
    () =>
      dist && colors
        ? buildDistributionOption(dist, { min: filter.min_value, max: filter.max_value }, metric.data_type, colors)
        : null,
    [dist, colors, filter.min_value, filter.max_value, metric.data_type],
  );

  const commit = (which: "min" | "max", text: string) => {
    const parsed = parseBound(text, isPercent);
    if (parsed === undefined) return; // invalid → no commit
    const current = which === "min" ? filter.min_value : filter.max_value;
    if (parsed !== current) onEditBound(which, parsed);
  };

  const presets = (metric.presets ?? []).filter((p) => p.min_value !== null || p.max_value !== null);
  const matches = (p: { min_value: number | null; max_value: number | null }) =>
    filter.min_value === p.min_value && filter.max_value === p.max_value;
  const unit = isPercent ? "%" : "";

  return (
    <section className="border-t border-border bg-surface-2 ix-pad">
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 className="ix-label m-0">Distribution — {metric.name}</h3>
        <span className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>
        <div className="ml-auto flex items-center gap-px">
          <button type="button" onClick={() => onMove("up")} disabled={!canMoveUp}
            aria-label={`Move ${metric.name} up`}
            className="h-[28px] w-7 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover disabled:opacity-30 disabled:cursor-not-allowed">↑</button>
          <button type="button" onClick={() => onMove("down")} disabled={!canMoveDown}
            aria-label={`Move ${metric.name} down`}
            className="h-[28px] w-7 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover disabled:opacity-30 disabled:cursor-not-allowed">↓</button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
        {/* Histogram — width-controlled so it never stretches on wide screens */}
        <div className="w-full max-w-[560px]">
          {option ? (
            <EChart option={option} className="h-[150px]" />
          ) : (
            <p className="h-[150px] flex items-center justify-center bg-zebra text-[13px] text-text-muted">
              No metric data yet — run the metrics job.
            </p>
          )}
          {presets.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {presets.map((p) => (
                <button key={p.name} type="button" onClick={() => onApplyPreset(p.min_value, p.max_value)}
                  aria-pressed={matches(p)}
                  className={`inline-flex h-[22px] items-center border px-2.5 text-[11px] font-bold transition-colors ${
                    matches(p) ? "bg-accent-wash border-accent text-accent" : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
                  }`}>{p.name}</button>
              ))}
            </div>
          )}
        </div>

        {/* Min / Max — commit on Enter/blur; mirror the grid's inline edit */}
        <div className="flex items-end gap-3.5 text-[12px] text-text-secondary">
          {(["min", "max"] as const).map((which) => {
            const text = which === "min" ? minText : maxText;
            const setText = which === "min" ? setMinText : setMaxText;
            return (
              <label key={which} className="flex w-[120px] flex-col gap-[5px]">
                <span className={FIELD_LABEL_CLASS}>{which === "min" ? "Min" : "Max"}</span>
                <div className="flex h-[34px] items-center bg-field border-b border-border-strong focus-within:border-b-2 focus-within:border-b-accent">
                  <input value={text} onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") commit(which, text); }}
                    onBlur={() => commit(which, text)} placeholder="—"
                    aria-label={`${which === "min" ? "Minimum" : "Maximum"} ${metric.name}${isPercent ? " in percent" : ""}`}
                    className="h-full w-full border-none bg-transparent px-2 text-right text-[13px] tabular-nums text-text-primary placeholder:text-text-muted outline-none" />
                  {unit && <span className="px-2 text-[11px] text-text-muted">{unit}</span>}
                </div>
              </label>
            );
          })}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/screener/DistributionPanel.tsx
git commit -m "feat(screener): DistributionPanel (active-row histogram, width-controlled)"
```

### Task 8: `MetricBrowserPopover.tsx` + `AddMetricBar.tsx`

The Barchart-style "Add a metric" bar: a typeahead for fast add + a categorized popover. Both call
`onToggleMetric` (add when unselected, remove when selected) — `BuildPanel` maps that to
`putScreenFilter({min:null,max:null})` / `deleteScreenFilter` (auto-save).

**Files:**
- Create: `frontend/src/components/screener/MetricBrowserPopover.tsx`
- Create: `frontend/src/components/screener/AddMetricBar.tsx`

- [ ] **Step 1: Implement the popover**

```tsx
"use client";

import { useMemo, useState } from "react";

import type { MetricDef } from "@/lib/api/client";
import { INPUT_CLASS } from "@/components/screener/shared";

export function MetricBrowserPopover({
  catalog,
  selectedCodes,
  pendingCode,
  onToggleMetric,
  onClose,
}: {
  catalog: MetricDef[];
  selectedCodes: ReadonlySet<string>;
  pendingCode: string | undefined;
  onToggleMetric: (code: string) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle === "" ? catalog : catalog.filter((m) =>
      m.name.toLowerCase().includes(needle) || m.code.toLowerCase().includes(needle) || m.abbreviation.toLowerCase().includes(needle));
    const map = new Map<string, MetricDef[]>();
    for (const m of filtered) (map.get(m.category) ?? map.set(m.category, []).get(m.category)!).push(m);
    return [...map.entries()];
  }, [catalog, search]);

  return (
    <div role="dialog" aria-label="Browse metrics by category"
      className="absolute z-20 mt-1 w-[360px] max-h-[420px] overflow-auto bg-surface-2 border border-border-strong shadow-[2px_2px_0_rgba(0,0,0,0.08)]">
      <div className="sticky top-0 flex items-center gap-2 bg-surface-2 border-b border-border px-3 py-2">
        <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter…"
          aria-label="Filter metrics" className={`flex-1 ${INPUT_CLASS} text-[12px]`} />
        <span className="tabular-nums text-[11px] text-text-muted">{catalog.length} metrics</span>
        <button type="button" onClick={onClose} aria-label="Close" className="px-1.5 text-text-muted hover:text-text-primary">×</button>
      </div>
      {groups.map(([category, metrics]) => {
        const selectedInGroup = metrics.filter((m) => selectedCodes.has(m.code)).length;
        return (
          <div key={category} className="border-b border-border last:border-b-0">
            <div className="flex items-center justify-between px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.06em] text-accent">
              <span>{category}</span>
              <span className="tabular-nums font-normal text-text-muted">{selectedInGroup}/{metrics.length}</span>
            </div>
            <ul className="pb-1">
              {metrics.map((m) => {
                const on = selectedCodes.has(m.code);
                return (
                  <li key={m.code}>
                    <button type="button" onClick={() => onToggleMetric(m.code)} disabled={pendingCode === m.code} aria-pressed={on}
                      className={`w-full flex items-center gap-2 px-3 py-1 text-left text-[12.5px] transition-colors disabled:opacity-50 ${on ? "text-accent" : "text-text-secondary hover:bg-layer-hover"}`}>
                      <span aria-hidden="true" className={`inline-flex h-[13px] w-[13px] shrink-0 items-center justify-center border text-[9px] ${on ? "bg-accent border-accent text-on-accent" : "border-border-strong"}`}>{on ? "✓" : ""}</span>
                      <span className={on ? "font-semibold" : ""}>{m.name}</span>
                      <span className="ml-auto text-[11px] text-text-muted">{m.abbreviation}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Implement the bar (typeahead + Browse trigger)**

```tsx
"use client";

import { useMemo, useRef, useState } from "react";

import type { MetricDef } from "@/lib/api/client";
import { INPUT_CLASS, BUTTON_CLASS } from "@/components/screener/shared";
import { MetricBrowserPopover } from "@/components/screener/MetricBrowserPopover";

export function AddMetricBar({
  catalog,
  selectedCodes,
  pendingCode,
  onToggleMetric,
}: {
  catalog: MetricDef[];
  selectedCodes: ReadonlySet<string>;
  pendingCode: string | undefined;
  onToggleMetric: (code: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Typeahead suggestions: not-yet-selected metrics matching the query.
  const suggestions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return [];
    return catalog
      .filter((m) => !selectedCodes.has(m.code))
      .filter((m) => m.name.toLowerCase().includes(needle) || m.abbreviation.toLowerCase().includes(needle) || m.code.toLowerCase().includes(needle))
      .slice(0, 8);
  }, [catalog, selectedCodes, query]);

  const add = (code: string) => { onToggleMetric(code); setQuery(""); };

  return (
    <div ref={wrapRef} className="relative flex flex-wrap items-center gap-2 bg-surface-2 border-b border-border px-[var(--ix-pad)] py-2.5">
      <span className="ix-label m-0">Add metric</span>
      <div className="relative w-[280px]">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a metric…  (P/E, ROE, Beta…)"
          aria-label="Find a metric by name or code" className={`w-full ${INPUT_CLASS} text-[12px]`} />
        {suggestions.length > 0 && (
          <ul className="absolute z-20 mt-px w-full max-h-[260px] overflow-auto bg-surface-2 border border-border-strong">
            {suggestions.map((m) => (
              <li key={m.code}>
                <button type="button" onClick={() => add(m.code)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] text-text-secondary hover:bg-layer-hover">
                  <span>{m.name}</span>
                  <span className="ml-auto text-[11px] text-text-muted">{m.abbreviation} · {m.category}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <button type="button" onClick={() => setBrowsing((v) => !v)} aria-expanded={browsing}
        className={`${BUTTON_CLASS} text-[12px]`}>Browse by category ▾</button>
      {browsing && (
        <MetricBrowserPopover catalog={catalog} selectedCodes={selectedCodes} pendingCode={pendingCode}
          onToggleMetric={onToggleMetric} onClose={() => setBrowsing(false)} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + commit**

Run: `cd frontend && npm run typecheck` → PASS

```bash
git add frontend/src/components/screener/MetricBrowserPopover.tsx frontend/src/components/screener/AddMetricBar.tsx
git commit -m "feat(screener): AddMetricBar typeahead + MetricBrowserPopover"
```

### Task 9: `FiltersGrid.tsx` (thin DataGrid wrapper over the editable adapter)

Thin by design: builds the options from `screenFiltersToGridOptions` and renders the shared
`DataGrid`. All persistence callbacks come from `BuildPanel` (Task 11), which must memoize them so
the options `useMemo` is stable.

**Files:**
- Create: `frontend/src/components/screener/FiltersGrid.tsx`

- [ ] **Step 1: Implement**

```tsx
"use client";

import { useMemo } from "react";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { DataGrid } from "@/components/ui/DataGrid";
import { screenFiltersToGridOptions, type FiltersGridCallbacks } from "@/lib/grid/filtersGridOptions";

export function FiltersGrid({
  filters,
  catalog,
  builds,
  selectedForDelete,
  callbacks,
  className,
}: {
  filters: ScreenFilter[];
  catalog: Map<string, MetricDef>;
  builds: Map<string, MetricBuild>;
  selectedForDelete: ReadonlySet<string>;
  callbacks: FiltersGridCallbacks;
  className?: string;
}) {
  const options = useMemo(
    () => screenFiltersToGridOptions(filters, catalog, builds, selectedForDelete, callbacks),
    [filters, catalog, builds, selectedForDelete, callbacks],
  );
  return <DataGrid options={options} className={className} />;
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run typecheck` → PASS

```bash
git add frontend/src/components/screener/FiltersGrid.tsx
git commit -m "feat(screener): FiltersGrid (DataGrid over editable adapter)"
```

### Task 10: `ScreenerHeader.tsx` (persistent header: switcher + count + save + actions)

Replaces `ScreenStrip` as the persistent top bar. Owns screen-CRUD mutations (same pattern as the
current `ScreenStrip`: `createScreen`/`patchScreen`/`deleteScreen`, invalidate `["screens"]`). The
global actions Reset/Export and the live count/save status are passed in from `ScreenerView`.

**Files:**
- Create: `frontend/src/components/screener/ScreenerHeader.tsx`

- [ ] **Step 1: Implement**

```tsx
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createScreen, deleteScreen, patchScreen, type ScreenListItem } from "@/lib/api/client";
import { BUTTON_CLASS, BUTTON_PRIMARY_CLASS, INPUT_CLASS } from "@/components/screener/shared";
import { formatCompact } from "@/lib/format";

type SaveStatus = "idle" | "saving" | "error";

export function ScreenerHeader({
  screens,
  selected,
  onSelect,
  headline,
  saveStatus,
  onReset,
  onExport,
  exporting,
}: {
  screens: ScreenListItem[];
  selected: ScreenListItem | null;
  onSelect: (id: number | null) => void;
  headline: number | null;
  saveStatus: SaveStatus;
  onReset: () => void;
  onExport: () => void;
  exporting: boolean;
}) {
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState("");

  const invalidateList = () => queryClient.invalidateQueries({ queryKey: ["screens"] });

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => patchScreen(id, { name }),
    onSuccess: (screen, { id }) => { setRenaming(false); invalidateList(); queryClient.setQueryData(["screen", id], screen); },
  });
  const createMutation = useMutation({
    mutationFn: (name: string) => createScreen({ name }),
    onSuccess: (screen) => { invalidateList(); queryClient.setQueryData(["screen", screen.id], screen); setMenuOpen(false); onSelect(screen.id); },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteScreen(id),
    onSuccess: (_r, id) => {
      invalidateList();
      for (const key of [["screen", id], ["screen-build", id], ["screen-results", id]]) queryClient.removeQueries({ queryKey: key });
      setMenuOpen(false);
      onSelect(null);
    },
  });

  const mutationError = renameMutation.error ?? createMutation.error ?? deleteMutation.error;

  return (
    <header className="sticky top-0 z-10 bg-surface-1 border-b border-border">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-2.5 px-[var(--ix-pad)] py-2.5">
        {/* Screen switcher */}
        <div className="relative">
          {renaming && selected ? (
            <input autoFocus value={draftName} onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draftName.trim()) renameMutation.mutate({ id: selected.id, name: draftName.trim() });
                else if (e.key === "Escape") setRenaming(false);
              }} onBlur={() => setRenaming(false)} aria-label="Rename screen" className={`w-[200px] ${INPUT_CLASS}`} />
          ) : (
            <button type="button" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen}
              className="inline-flex items-center gap-1.5 text-[15px] font-bold text-text-primary hover:text-accent">
              <span aria-hidden="true">⌂</span>{selected ? selected.name : "Untitled screen"}<span aria-hidden="true" className="text-text-muted">▾</span>
            </button>
          )}
          {menuOpen && (
            <div role="menu" className="absolute z-20 mt-1 w-[240px] bg-surface-2 border border-border-strong">
              <ul className="max-h-[240px] overflow-auto py-1">
                {screens.map((s) => (
                  <li key={s.id}>
                    <button type="button" role="menuitem" onClick={() => { onSelect(s.id); setMenuOpen(false); }}
                      className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] ${s.id === selected?.id ? "text-accent font-semibold" : "text-text-secondary hover:bg-layer-hover"}`}>
                      {s.name}<span className="ml-auto tabular-nums text-[10px] text-text-muted">{s.filter_count}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex flex-col border-t border-border p-1 text-[12px]">
                <button type="button" onClick={() => { const name = window.prompt("New screen name"); if (name?.trim()) createMutation.mutate(name.trim()); }}
                  className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">+ New screen</button>
                {selected && (
                  <>
                    <button type="button" onClick={() => { setDraftName(selected.name); setRenaming(true); setMenuOpen(false); }}
                      className="px-2 py-1 text-left text-text-secondary hover:bg-layer-hover">Rename</button>
                    <button type="button" onClick={() => { if (window.confirm(`Delete screen "${selected.name}"?`)) deleteMutation.mutate(selected.id); }}
                      className="px-2 py-1 text-left text-loss hover:bg-layer-hover">Delete</button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Live match count */}
        <span aria-live="polite" className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>

        {/* Auto-save status (NOT a save button — persistence is live) */}
        <span aria-live="polite" className="text-[11px] text-text-muted">
          {saveStatus === "saving" ? "Saving…" : saveStatus === "error" ? "Save failed — retry" : "Saved ✓"}
        </span>

        {/* Global actions */}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onReset} disabled={!selected} className={BUTTON_CLASS}>Reset</button>
          <button type="button" onClick={onExport} disabled={!selected || exporting} className={`${BUTTON_PRIMARY_CLASS} inline-flex items-center gap-[7px]`}>
            {exporting ? "Exporting…" : "⬇ Export CSV"}
          </button>
        </div>
      </div>
      {mutationError && (
        <p role="alert" className="mx-auto max-w-[1360px] px-[var(--ix-pad)] pb-2 text-[12px] text-loss">{mutationError.message}</p>
      )}
    </header>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run typecheck` → PASS

```bash
git add frontend/src/components/screener/ScreenerHeader.tsx
git commit -m "feat(screener): persistent ScreenerHeader (switcher + count + save status + actions)"
```

### Task 11: `BuildPanel.tsx` (orchestrator — merges Select Metrics + Build)

The brain: owns the batch-build query, the filter mutations (edit/remove/reorder/add with
lazy screen creation), the active-row + bulk-select state, the empty state, and composes
`AddMetricBar` + `FiltersGrid` + `DistributionPanel`. Reports `headline`/`saveStatus` up to
`ScreenerView` (which feeds the header).

**Files:**
- Modify: `frontend/src/components/screener/shared.tsx` (extend `applyFilterResponse`)
- Create: `frontend/src/components/screener/BuildPanel.tsx`

- [ ] **Step 1: Extend `applyFilterResponse` to invalidate the batch build**

In `shared.tsx`, add one line to `applyFilterResponse` so the sparklines/distribution refresh after
add/remove/edit:

```typescript
export function applyFilterResponse(
  queryClient: QueryClient,
  screenId: number,
  resp: FilterUpdateResponse,
): void {
  queryClient.setQueryData(["screen", screenId], resp.screen);
  queryClient.invalidateQueries({ queryKey: ["screens"] });
  queryClient.invalidateQueries({ queryKey: ["screen-results", screenId] });
  queryClient.invalidateQueries({ queryKey: ["screen-build", screenId] }); // batch build (sparklines + panel)
}
```

- [ ] **Step 2: Implement `BuildPanel`**

```tsx
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createScreen,
  deleteScreenFilter,
  fetchScreenBuildAll,
  putScreenFilter,
  reorderScreenFilters,
  type FilterBody,
  type MetricDef,
  type Screen,
} from "@/lib/api/client";
import { AddMetricBar } from "@/components/screener/AddMetricBar";
import { DistributionPanel } from "@/components/screener/DistributionPanel";
import { FiltersGrid } from "@/components/screener/FiltersGrid";
import { applyFilterResponse, ErrorPanel, retryPolicy } from "@/components/screener/shared";
import type { FiltersGridCallbacks } from "@/lib/grid/filtersGridOptions";

type SaveStatus = "idle" | "saving" | "error";

export function BuildPanel({
  screen,
  catalog,
  onScreenCreated,
  onHeadline,
  onSaveStatus,
}: {
  screen: Screen | null;
  catalog: MetricDef[];
  onScreenCreated: (id: number) => void;
  onHeadline: (count: number | null) => void;
  onSaveStatus: (status: SaveStatus) => void;
}) {
  const queryClient = useQueryClient();
  const screenId = screen?.id ?? null;

  const catalogMap = useMemo(() => new Map(catalog.map((m) => [m.code, m])), [catalog]);
  const filters = useMemo(
    () => (screen ? [...screen.filters].sort((a, b) => a.position - b.position) : []),
    [screen],
  );
  const filterCodes = useMemo(() => new Set(filters.map((f) => f.metric_code)), [filters]);

  const buildQuery = useQuery({
    queryKey: ["screen-build", screenId],
    queryFn: ({ signal }) => fetchScreenBuildAll(screenId as number, signal),
    enabled: screenId !== null,
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const builds = useMemo(
    () => new Map((buildQuery.data?.metrics ?? []).map((m) => [m.metric_code, m])),
    [buildQuery.data],
  );

  // Live headline: batch-build first, overwritten by each mutation response.
  const headline = buildQuery.data?.headline_count ?? null;
  useEffect(() => onHeadline(headline), [headline, onHeadline]);

  const [activeCode, setActiveCode] = useState<string | null>(null);
  const [selectedForDelete, setSelectedForDelete] = useState<ReadonlySet<string>>(new Set());

  // Keep the active row valid (default to the first filter; clear when none).
  useEffect(() => {
    if (filters.length === 0) setActiveCode(null);
    else if (activeCode === null || !filterCodes.has(activeCode)) setActiveCode(filters[0].metric_code);
  }, [filters, filterCodes, activeCode]);

  const reportSaving = (s: SaveStatus) => onSaveStatus(s);

  const putMutation = useMutation({
    mutationFn: ({ code, body }: { code: string; body: FilterBody }) => putScreenFilter(screenId as number, code, body),
    onMutate: () => reportSaving("saving"),
    onSuccess: (resp) => { applyFilterResponse(queryClient, screenId as number, resp); onHeadline(resp.headline_count); reportSaving("idle"); },
    onError: () => reportSaving("error"),
  });
  const removeMutation = useMutation({
    mutationFn: (code: string) => deleteScreenFilter(screenId as number, code),
    onMutate: () => reportSaving("saving"),
    onSuccess: (resp) => { applyFilterResponse(queryClient, screenId as number, resp); onHeadline(resp.headline_count); reportSaving("idle"); },
    onError: () => reportSaving("error"),
  });
  const reorderMutation = useMutation({
    mutationFn: (codes: string[]) => reorderScreenFilters(screenId as number, codes),
    onMutate: () => reportSaving("saving"),
    onSuccess: (s) => {
      queryClient.setQueryData(["screen", s.id], s);
      queryClient.invalidateQueries({ queryKey: ["screen-results", s.id] });
      reportSaving("idle");
    },
    onError: () => reportSaving("error"),
  });

  // Add (or toggle off) a metric. Lazy-creates an "Untitled screen" on first add.
  const toggleMetric = useCallback(
    async (code: string) => {
      if (filterCodes.has(code)) { removeMutation.mutate(code); return; }
      try {
        reportSaving("saving");
        let id = screenId;
        if (id === null) {
          const created = await createScreen({ name: "Untitled screen" });
          id = created.id;
          queryClient.setQueryData(["screen", id], created);
          queryClient.invalidateQueries({ queryKey: ["screens"] });
          onScreenCreated(id);
        }
        const resp = await putScreenFilter(id, code, { min_value: null, max_value: null });
        applyFilterResponse(queryClient, id, resp);
        onHeadline(resp.headline_count);
        setActiveCode(code);
        reportSaving("idle");
      } catch { reportSaving("error"); }
    },
    [filterCodes, screenId, queryClient, onScreenCreated, onHeadline, removeMutation],
  );

  const editBound = useCallback(
    (code: string, which: "min" | "max", value: number | null) => {
      const f = filters.find((x) => x.metric_code === code);
      if (!f) return;
      putMutation.mutate({
        code,
        body: { min_value: which === "min" ? value : f.min_value, max_value: which === "max" ? value : f.max_value },
      });
    },
    [filters, putMutation],
  );

  const move = useCallback(
    (code: string, direction: "up" | "down") => {
      const codes = filters.map((f) => f.metric_code);
      const i = codes.indexOf(code);
      const j = direction === "up" ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= codes.length) return;
      [codes[i], codes[j]] = [codes[j], codes[i]];
      reorderMutation.mutate(codes);
    },
    [filters, reorderMutation],
  );

  const toggleSelect = useCallback((code: string, checked: boolean) => {
    setSelectedForDelete((prev) => {
      const next = new Set(prev);
      if (checked) next.add(code); else next.delete(code);
      return next;
    });
  }, []);

  const gridCallbacks: FiltersGridCallbacks = useMemo(
    () => ({
      onEditBound: editBound,
      onRemove: (code) => removeMutation.mutate(code),
      onMove: move,
      onToggleSelect: toggleSelect,
      onSelectRow: setActiveCode,
    }),
    [editBound, move, toggleSelect, removeMutation],
  );

  const deleteSelected = () => {
    if (screenId === null) return;
    for (const code of selectedForDelete) removeMutation.mutate(code);
    setSelectedForDelete(new Set());
  };

  const pendingCode = putMutation.isPending ? putMutation.variables?.code : undefined;

  // ── render ──────────────────────────────────────────────────────────
  const activeFilter = filters.find((f) => f.metric_code === activeCode) ?? null;
  const activeMetric = activeCode ? catalogMap.get(activeCode) : undefined;

  return (
    <section className="mx-auto max-w-[1360px] flex flex-col">
      <AddMetricBar catalog={catalog} selectedCodes={filterCodes} pendingCode={pendingCode} onToggleMetric={toggleMetric} />

      {filters.length === 0 ? (
        <div className="bg-surface-2 border-x border-b border-border px-6 py-12 text-center text-[13px] text-text-muted">
          No metrics yet — add one above to start building your screen.
          <div className="mt-2 text-[11px] text-text-muted">① Name &nbsp;→&nbsp; ② Add metrics &amp; set ranges &nbsp;→&nbsp; ③ See results</div>
        </div>
      ) : buildQuery.isError ? (
        <ErrorPanel title="Failed to load distributions" message={buildQuery.error.message} onRetry={() => buildQuery.refetch()} />
      ) : (
        <>
          {selectedForDelete.size > 0 && (
            <div className="bg-surface-2 border-x border-b border-border px-[var(--ix-pad)] py-2">
              <button type="button" onClick={deleteSelected}
                className="border border-loss text-loss bg-field px-2.5 py-1 text-[11px] font-bold hover:bg-loss-muted">
                Delete {selectedForDelete.size} selected
              </button>
            </div>
          )}
          <FiltersGrid filters={filters} catalog={catalogMap} builds={builds} selectedForDelete={selectedForDelete}
            callbacks={gridCallbacks} className="border-x border-border" />
          {activeFilter && activeMetric && (
            <DistributionPanel
              metric={activeMetric}
              filter={activeFilter}
              build={builds.get(activeFilter.metric_code)}
              headline={headline}
              canMoveUp={filters[0].metric_code !== activeFilter.metric_code}
              canMoveDown={filters[filters.length - 1].metric_code !== activeFilter.metric_code}
              onEditBound={(which, value) => editBound(activeFilter.metric_code, which, value)}
              onApplyPreset={(min, max) => putMutation.mutate({ code: activeFilter.metric_code, body: { min_value: min, max_value: max } })}
              onMove={(dir) => move(activeFilter.metric_code, dir)}
            />
          )}
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Typecheck + commit**

Run: `cd frontend && npm run typecheck` → PASS

```bash
git add frontend/src/components/screener/shared.tsx frontend/src/components/screener/BuildPanel.tsx
git commit -m "feat(screener): BuildPanel orchestrator (merge Select Metrics + Build)"
```

---

## FASE D — Integration + cleanup

### Task 12: Refactor `ScreenerView` (header + 2 tabs) + trim `ResultsTab`

**Files:**
- Modify (replace body): `frontend/src/components/screener/ScreenerView.tsx`
- Modify: `frontend/src/components/screener/ResultsTab.tsx`

- [ ] **Step 1: Replace `ScreenerView.tsx`**

```tsx
"use client";

/**
 * Screener workspace: a persistent header (screen switcher + live count + save
 * status + Reset/Export) over two tabs — Build (unified metric add + editable
 * filters grid + distribution panel) and Results (server-driven Grid Pro).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  deleteScreenFilter,
  fetchMetricCatalog,
  fetchScreen,
  fetchScreenResultsCsv,
  fetchScreens,
} from "@/lib/api/client";
import { BuildPanel } from "@/components/screener/BuildPanel";
import { ResultsTab } from "@/components/screener/ResultsTab";
import { ScreenerHeader } from "@/components/screener/ScreenerHeader";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";

const TABS = [
  { id: "build", label: "Build" },
  { id: "results", label: "Results" },
] as const;
type TabId = (typeof TABS)[number]["id"];
type SaveStatus = "idle" | "saving" | "error";

export function ScreenerView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab: TabId = searchParams.get("tab") === "results" ? "results" : "build";
  const setTab = (next: TabId) => router.replace(`/screener?tab=${next}`, { scroll: false });

  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [headline, setHeadline] = useState<number | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [exporting, setExporting] = useState(false);

  const screensQuery = useQuery({ queryKey: ["screens"], queryFn: ({ signal }) => fetchScreens(signal), staleTime: 60_000, retry: retryPolicy });
  const screens = screensQuery.data;
  useEffect(() => {
    if (!screens) return;
    if (screens.length === 0) setSelectedId(null);
    else if (selectedId === null || !screens.some((s) => s.id === selectedId)) setSelectedId(screens[0].id);
  }, [screens, selectedId]);
  const selected = screens?.find((s) => s.id === selectedId) ?? null;

  const screenQuery = useQuery({
    queryKey: ["screen", selectedId], queryFn: ({ signal }) => fetchScreen(selectedId as number, signal),
    enabled: selectedId !== null, staleTime: 60_000, retry: retryPolicy,
  });
  const catalogQuery = useQuery({ queryKey: ["screener-metrics"], queryFn: ({ signal }) => fetchMetricCatalog(signal), staleTime: Infinity, retry: retryPolicy });

  const onReset = async () => {
    const screen = screenQuery.data;
    if (!screen || screen.filters.length === 0 || !window.confirm("Clear all filters from this screen?")) return;
    setSaveStatus("saving");
    try {
      await Promise.all(screen.filters.map((f) => deleteScreenFilter(screen.id, f.metric_code)));
      for (const key of [["screen", screen.id], ["screen-build", screen.id], ["screen-results", screen.id], ["screens"]])
        queryClient.invalidateQueries({ queryKey: key });
      setSaveStatus("idle");
    } catch { setSaveStatus("error"); }
  };

  const onExport = async () => {
    if (selectedId === null) return;
    setExporting(true);
    try {
      const blob = await fetchScreenResultsCsv(selectedId, { dir: "asc" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(selected?.name ?? "screen").replace(/[^\w.-]+/g, "_")}-results.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  };

  if (screensQuery.isError) {
    return <div className="mx-auto max-w-[1360px] p-[var(--ix-pad)]"><ErrorPanel title="Failed to load screens" message={screensQuery.error.message} onRetry={() => screensQuery.refetch()} /></div>;
  }
  if (catalogQuery.isError) {
    return <div className="mx-auto max-w-[1360px] p-[var(--ix-pad)]"><ErrorPanel title="Failed to load metric catalog" message={catalogQuery.error.message} onRetry={() => catalogQuery.refetch()} /></div>;
  }

  return (
    <div className="flex flex-col pb-10">
      <ScreenerHeader screens={screens ?? []} selected={selected} onSelect={setSelectedId}
        headline={headline} saveStatus={saveStatus} onReset={onReset} onExport={onExport} exporting={exporting} />

      <div className="mx-auto w-full max-w-[1360px] px-[var(--ix-pad)]">
        <div role="tablist" aria-label="Screener views" className="mt-3 flex">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className={`h-[36px] px-5 text-[12.5px] border transition-colors ${
                tab === t.id ? "relative z-[1] bg-surface-2 border-border border-b-surface-2 font-bold text-accent"
                  : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
              }`}>{t.label}</button>
          ))}
        </div>
      </div>

      <div className="-mt-px">
        {tab === "build" ? (
          catalogQuery.data ? (
            <BuildPanel screen={screenQuery.data ?? null} catalog={catalogQuery.data}
              onScreenCreated={setSelectedId} onHeadline={setHeadline} onSaveStatus={setSaveStatus} />
          ) : (
            <div className="mx-auto max-w-[1360px] h-[320px] bg-surface-2 animate-pulse" />
          )
        ) : selected ? (
          <div className="mx-auto max-w-[1360px]">
            <ResultsTab screenId={selected.id} screenName={selected.name} onHeadline={setHeadline} />
          </div>
        ) : (
          <div className="mx-auto max-w-[1360px] px-6 py-12 text-center text-[13px] text-text-muted">
            Create a screen in the Build tab to see results.
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Trim `ResultsTab.tsx`**

Three edits to `ResultsTab.tsx`:

(a) Add the `onHeadline` prop to the signature:

```tsx
export function ResultsTab({
  screenId,
  screenName,
  onHeadline,
}: {
  screenId: number;
  screenName: string;
  onHeadline: (count: number | null) => void;
}) {
```

(b) Report the total upward (add after the `resultsQuery` declaration):

```tsx
  useEffect(() => {
    onHeadline(resultsQuery.data?.total ?? null);
  }, [resultsQuery.data?.total, onHeadline]);
```

(c) Remove the title row (the `<div>` holding the `Results` `h2`, the matches chip, and the **Export CSV** button — count + export now live in `ScreenerHeader`) AND the `exportCsv` handler + `exporting`/`exportError` state. Keep ONLY a slim search toolbar:

```tsx
      <div className="flex flex-wrap items-center gap-2.5 px-[var(--ix-pad)] py-3">
        <div className="relative w-[220px]">
          <input value={searchText} onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search ticker / name…" aria-label="Search results by ticker or name"
            className={`w-full pl-[30px] ${INPUT_CLASS} text-[12px]`} />
        </div>
      </div>
```

Leave the grid (`DataGrid`), the pagination footer, and the `screenResultsToGridOptions` wiring unchanged. Remove the now-unused `fetchScreenResultsCsv`, `BUTTON_CLASS`, and search-icon `svg` imports/markup if they become unused (typecheck/lint will flag them).

- [ ] **Step 3: Typecheck + run frontend tests**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: PASS (existing 18 + new adapter/bounds/sparkline tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/screener/ScreenerView.tsx frontend/src/components/screener/ResultsTab.tsx
git commit -m "feat(screener): unified workspace — persistent header + Build|Results tabs"
```

### Task 13: Remove the merged wizard tabs + final verification

**Files:**
- Delete: `frontend/src/components/screener/SelectMetricsTab.tsx`, `frontend/src/components/screener/BuildTab.tsx`
- Delete (if present): their test files.

- [ ] **Step 1: Confirm nothing imports them**

Run: `cd frontend && grep -rn "SelectMetricsTab\|BuildTab" src/ || echo "no references"`
Expected: `no references` (ScreenerView no longer imports them).

- [ ] **Step 2: Delete the files**

```bash
git rm frontend/src/components/screener/SelectMetricsTab.tsx frontend/src/components/screener/BuildTab.tsx
```

- [ ] **Step 3: Full verification (frontend + backend)**

Run:
```bash
cd frontend && npm run typecheck && npm run lint && npm run test
cd ../backend && pytest -q
```
Expected: all green (frontend types/lint/vitest; backend pytest including the 5 new screener route tests). If `ScreenStrip` is now unused, either delete it too (after a `grep`) or leave it — note the decision.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(screener): remove merged SelectMetricsTab + BuildTab"
```

- [ ] **Step 5 (optional): Manual smoke**

Run `npm run dev --prefix frontend`, open `/screener`: empty state → add a metric (typeahead + Browse) → edit Min/Max inline → reorder ↑/↓ → check Results columns follow the order → Export CSV → Reset.

---

## Self-Review (author checklist — completed)

- **Spec coverage:** empty state (inline coaching) → Task 11; dense metric selector (typeahead + popover) → Task 8; merged Build (Select+Build) → Tasks 7-11; persistent header → Task 10/12; auto-save → Tasks 9-12 (mutations + `applyFilterResponse`); editable filters Grid Pro → Tasks 6/9; sparkline + bottom panel (width-controlled) → Tasks 5/7; reorder endpoint → Task 1; batch build → Task 2; `resultsQuery` transition (unchanged key) → Task 12. ✓
- **Type consistency:** `FiltersGridCallbacks` (`onEditBound`/`onRemove`/`onMove`/`onToggleSelect`/`onSelectRow`) is defined in Task 6 and consumed verbatim in Tasks 9/11; `MetricBuild`/`BuildAll` types from Task 3 used in Tasks 6/7/11; `reorderScreenFilters`/`fetchScreenBuildAll` from Task 3 used in Task 11. ✓
- **Placeholders:** none — every code step carries full code. Two intentional "verify against generated `api.d.ts`" notes in Task 3 (the openapi-typescript alias names) and one "confirm export command" — these are real lookups, not deferred work.
- **Known risk:** Grid Pro `editMode`/`renderer:checkbox`/`events.afterEdit` API is taken from the repo's `positionsGridOptions.ts`/`universeGridOptions.ts` (grid-rollout) — confirm the exact `afterEdit` value semantics (empty-cell → null) when implementing Task 6; tests assert behavior.

---

## Deferred to a follow-up (phase 2)

These design-spec items were intentionally NOT in the Tasks 1–13 scope and are deferred (no runtime impact on the shipped workspace):

- **"Duplicate screen" action** in the `ScreenSwitcher` (design doc §"ScreenSwitcher", lines ~109/164). `ScreenerHeader` ships New / Rename / Delete; Duplicate (create a new screen seeded from the current screen's filters) is a follow-up.
- **`aria-invalid` feedback on invalid bound entry** (design doc lines ~151/218/241). Invalid Min/Max input is currently dropped without committing (`parseBound` → `undefined` → no-op) but does not surface an `aria-invalid`/visual cue on the grid cell or the `DistributionPanel` inputs. Follow-up a11y polish.

Component tests for the new orchestrators (`BuildPanel`, `ScreenerHeader`) were ADDED post-Task-13 (RTL + jsdom infra) and are no longer deferred.

