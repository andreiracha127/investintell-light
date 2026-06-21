# COMBO Sprint 4 — Macro page (quadrant + live gate + bands + haven tilt) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the COMBO regime machinery on the Macro page: extend `GET /macro/regime` with a `macro_quadrant` block (current quadrant + growth/inflation scores/states, the live GATE state + trend/credit/drawdown votes + dwell_days, the resulting combined regime, the per-class bands, and the haven tilt when SLOWDOWN), regenerate the frontend types, and render quadrant + gate + bands in `MacroRegimeView` (the existing composite detector stays the page's headline — decision O3). **Decision A (spec §9):** the quadrant + growth/inflation scores are READ from `regime_gate_daily` (worker-materialized — single source of truth shared with the builder), NOT computed in the route from proxies (the backend lacks TIP/IEF). The SLOWDOWN→goldfix haven tilt is ACTIVE (not degraded to None) whenever the worker has materialized a SLOWDOWN quadrant. **Done when:** the route returns the new block (it degrades to `quadrant=None` only when the gate row itself lacks a quadrant, e.g. pre-backfill), `pnpm run types` regenerates the schema, and `MacroRegimeView` shows the gate + quadrant + bands with a green frontend gate.

**Architecture:** The backend handler `get_macro_regime` (`backend/app/api/routes/macro.py:42-97`) gains a `macro_quadrant: MacroQuadrantOut | None` field built from `taa_bands.fetch_gate_regime` (which returns the gate state AND the worker-materialized `quadrant`/`growth_score`/`inflation_score` — decision A) + `taa_bands.combined_regime` + `taa_bands.effective_class_bands` (+ `goldfix_target` when SLOWDOWN). The composite read is UNCHANGED (it remains the headline detector; the gate is an ADDED block). The frontend regenerates `api.d.ts` via `pnpm run types`, re-exports a `MacroQuadrant` type, adds a pure Highcharts bands builder (mirroring `buildHcDriftBandsOption`), and renders a new section in `MacroRegimeView` next to the existing RRG.

**Tech Stack:** FastAPI/Pydantic v2 (backend), Next.js/React Query, Highcharts 13, vitest+jsdom, openapi-typescript. Repos `E:/investintell-light/backend` and `E:/investintell-light/frontend`.

## Repo & base branch

- Runs in `E:/investintell-light/backend` (route + schema) and `E:/investintell-light/frontend` (types + UI), on branch `feat/combo-regime-allocator`, based on `feat/bl-amplo-constraints-drift`. Depends on Sprint 2 (`taa_bands`) being committed on this branch (and benefits from Sprint 1's `regime_gate_daily` being populated, but degrades to gate-empty gracefully).
- **The implementer must NOT create/switch branches** (shared working tree). Commit on the current branch.

## Architecture (components touched)

- **MODIFY** `backend/app/schemas/macro.py` — add `ClassBandOut`, `GateBlockOut`, `MacroQuadrantOut`; add `macro_quadrant: MacroQuadrantOut | None = None` to `MacroRegimeResponse` (`macro.py:39-57`).
- **MODIFY** `backend/app/api/routes/macro.py` — build the `macro_quadrant` block in `get_macro_regime` (`macro.py:42-97`); the route already injects `datalake` via `Depends(get_datalake_session)`.
- **REGENERATE** `backend/openapi.json` → `frontend/src/lib/api/api.d.ts` (via `pnpm run types`).
- **MODIFY** `frontend/src/lib/api/client.ts` — re-export `MacroQuadrant` (the `fetchMacroRegime` return already carries it once types regenerate).
- **NEW** `frontend/src/lib/charts/hc/macro-bands.ts` — pure per-class bands chart builder (mirror `buildHcDriftBandsOption`, `src/lib/charts/hc/rebalance.ts:52`).
- **MODIFY** `frontend/src/components/macro/MacroRegimeView.tsx` — a new section showing gate + quadrant + bands (no existing test file — Task 5 creates the first one).

## Global Constraints

- **The composite stays the headline detector (O3).** The gate is an ADDED block; do NOT replace `fetch_composite_regime` in the route. The route's existing 404-when-unmaterialized behavior for the COMPOSITE is unchanged; the gate block is best-effort (None when `regime_gate_daily` is empty).
- **Bands shown = the 4 classes** `equity / fixed_income / alternatives / cash` (no `multi_asset` — O5).
- **Quadrant source — RESOLVED (decision A, spec §9):** the quadrant + growth/inflation scores are READ from `regime_gate_daily` (materialized by the Sprint-1 worker, which fetches SPY/HYG/IEF/TIP) via `taa_bands.fetch_gate_regime`. The route does NOT compute the quadrant from proxies (TIP/IEF are NOT in `eod_prices` — verified) and does NOT call `macro_quadrant_from_proxies`. The block degrades to `quadrant=None` (regime gate-only → RISK_ON/RISK_OFF) ONLY when the gate row itself has no quadrant (pre-backfill); once the worker has run, the quadrant + SLOWDOWN→goldfix tilt are live. Single source of truth shared with the builder (Sprint 3).
- **Colors via tokens** (`chartColors()`, `frontend/src/lib/charts/chartColors.ts`) — no hardcoded hex. Use the `TEST_COLORS` fixture (`src/lib/charts/hc/__fixtures__/colors.ts`, verified to exist) in builder tests.
- **Types are generated:** `pnpm run types` = `openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts` (verified). **Sequence it AFTER the backend schema change**, before the frontend type-consuming tasks. Regenerate `backend/openapi.json` first via the project's export flow (find the export script, e.g. `scripts/export_openapi.py`; if absent, the app's OpenAPI is served at `/openapi.json` and `pnpm run types` reads the committed `backend/openapi.json`).
- **TDD.** **VERIFICATION COMMANDS (confirmed from `frontend/package.json`):** backend `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest`; frontend `cd /e/investintell-light/frontend && pnpm test` (= `vitest run`), `pnpm run typecheck` (= `tsc --noEmit`), `pnpm run lint` (= `eslint`), `pnpm run types`, `pnpm build` (= `next build --turbopack`).

---

### Task 1: Backend — `macro_quadrant` block on `/macro/regime`

**Files:**
- Modify: `backend/app/schemas/macro.py` (`MacroRegimeResponse` `macro.py:39-57`; new sub-schemas)
- Modify: `backend/app/api/routes/macro.py` (`get_macro_regime` `macro.py:42-97`)
- Test: `backend/tests/test_macro_quadrant_route.py`

**Interfaces:**
- Consumes: `taa_bands.fetch_gate_regime` (returns gate state + worker-materialized `quadrant`/`growth_score`/`inflation_score` — decision A), `taa_bands.combined_regime`, `taa_bands.effective_class_bands`, `taa_bands.goldfix_target` (Sprint 2). The route already has `datalake`. **Does NOT call `macro_quadrant_from_proxies` (decision A — the quadrant is read, not computed; no backend TIP/IEF).**
- Produces (new in `app/schemas/macro.py`):

```python
class ClassBandOut(BaseModel):
    asset_class: str
    min_weight: float
    max_weight: float


class GateBlockOut(BaseModel):
    as_of: dt.date | None
    state: str                       # 'risk_on' | 'risk_off'
    trend_vote: bool
    credit_vote: bool
    drawdown_vote: bool
    vote_count: int
    dwell_days: int


class MacroQuadrantOut(BaseModel):
    as_of: dt.date | None
    quadrant: str | None             # RECOVERY|EXPANSION|SLOWDOWN|CONTRACTION|None
    growth_state: str | None         # up|down
    inflation_state: str | None
    growth_score: float | None
    inflation_score: float | None
    combined_regime: str             # RISK_ON|RISK_OFF|INFLATION|STAG_GOLD
    bands: list[ClassBandOut]        # 4 classes (empty when STAG_GOLD haven)
    haven_tilt: dict[str, float] | None  # goldfix target when STAG_GOLD, else None
    gate: GateBlockOut | None        # None when regime_gate_daily empty
```

`MacroRegimeResponse` gains `macro_quadrant: MacroQuadrantOut | None = None`. Handler logic (added AFTER the existing composite assembly, not replacing it):
1. `gate = await taa_bands.fetch_gate_regime(datalake)`; `gate_state = gate.state if gate else None`.
2. quadrant (decision A — READ from the gate snapshot, NOT computed): `quadrant = gate.quadrant if gate else None`; `growth_score = gate.growth_score if gate else None`; `inflation_score = gate.inflation_score if gate else None`; derive `growth_state`/`inflation_state` as `"up"/"down"` from the score signs (or `None` when the score is `None`). The quadrant is the lowercase value from `regime_gate_daily`; `combined_regime` upper-normalizes it. NO `macro_quadrant_from_proxies` call.
3. `regime = taa_bands.combined_regime(gate_state, quadrant)`.
4. if `regime == "STAG_GOLD"`: `bands=[]`, `haven_tilt = taa_bands.goldfix_target(<available haven names>)` (in the route, the available set is unknown → pass the full goldfix name set so the tilt shows the conviction target; document that the realized tilt depends on the builder universe). else: `bands = [ClassBandOut(asset_class=c, min_weight=lo, max_weight=hi) for c,(lo,hi) in effective_class_bands(regime)[0].items()]`, `haven_tilt=None`.
5. `gate_block = GateBlockOut(...)` from `gate` (None when `gate is None`).
6. attach `macro_quadrant=MacroQuadrantOut(...)`.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_macro_quadrant_route.py`:

```python
import pytest
from app.services import taa_bands as tb


@pytest.mark.asyncio
async def test_macro_regime_includes_gate_block(monkeypatch, client, seeded_composite):
    # seeded_composite: the existing fixture that makes fetch_composite_regime
    # return a snapshot so the route doesn't 404 (reuse the macro route test setup).
    async def _gate(*a, **k):
        return tb.GateRegimeSnapshot(as_of=None, state="risk_off", vote_count=2,
                                     trend_vote=True, credit_vote=True,
                                     drawdown_vote=False, dwell_days=30, last_flip=None,
                                     growth_score=-0.03, inflation_score=0.01,
                                     quadrant="slowdown")
    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    # gate risk_off dominates over the quadrant => combined regime RISK_OFF, 4 bands
    assert mq["combined_regime"] == "RISK_OFF"
    assert mq["gate"]["state"] == "risk_off"
    assert mq["gate"]["dwell_days"] == 30
    # the worker-materialized quadrant is surfaced even when the gate dominates the bands
    assert mq["quadrant"] == "slowdown"
    eq = next(b for b in mq["bands"] if b["asset_class"] == "equity")
    # RISK_OFF equity: center .38 hw .08*1.5=.12 -> [0.26, 0.50]
    assert abs(eq["min_weight"] - 0.26) < 1e-6
    assert abs(eq["max_weight"] - 0.50) < 1e-6


@pytest.mark.asyncio
async def test_macro_regime_slowdown_quadrant_routes_to_haven(monkeypatch, client, seeded_composite):
    # gate risk_on + worker-materialized SLOWDOWN => STAG_GOLD haven tilt (decision A)
    async def _gate(*a, **k):
        return tb.GateRegimeSnapshot(as_of=None, state="risk_on", vote_count=0,
                                     trend_vote=False, credit_vote=False,
                                     drawdown_vote=False, dwell_days=80, last_flip=None,
                                     growth_score=-0.05, inflation_score=0.02,
                                     quadrant="slowdown")
    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    assert mq["quadrant"] == "slowdown"
    assert mq["combined_regime"] == "STAG_GOLD"
    assert mq["bands"] == []                 # haven bypasses class bands
    assert mq["haven_tilt"] and mq["haven_tilt"]["GLD"] > 0


@pytest.mark.asyncio
async def test_macro_regime_gate_empty_degrades(monkeypatch, client, seeded_composite):
    async def _no_gate(*a, **k):
        return None
    monkeypatch.setattr(tb, "fetch_gate_regime", _no_gate)
    resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    assert mq["gate"] is None
    # gate None + quadrant None => combined regime RISK_ON, still 4 bands
    assert mq["combined_regime"] == "RISK_ON"
    assert len(mq["bands"]) == 4
```

(Reuse the real macro route test fixture for `seeded_composite`/`client`; read `tests/test_macro_*` to find how the composite reader is seeded.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_macro_quadrant_route.py -v`
Expected: FAIL (`macro_quadrant` not in response).

- [ ] **Step 3: Implement** the sub-schemas + handler assembly (add the gate/quadrant block; leave the composite assembly untouched).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_macro_quadrant_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/macro.py backend/app/api/routes/macro.py backend/tests/test_macro_quadrant_route.py
git commit -m "Expose macro_quadrant (gate + combined regime + bands) on /macro/regime"
```

---

### Task 2: Regenerate frontend types + export `MacroQuadrant`

**Files:**
- Regenerate: `backend/openapi.json` (project export flow) → `frontend/src/lib/api/api.d.ts` (`pnpm run types`)
- Modify: `frontend/src/lib/api/client.ts` (re-export `MacroQuadrant`; `fetchMacroRegime` `client.ts:1424` already returns `MacroRegime` `client.ts:290-291`)

**Interfaces:**
- Consumes: the updated `MacroRegimeResponse` (Task 1).
- Produces: `export type MacroQuadrant = NonNullable<MacroRegime["macro_quadrant"]>;` in `client.ts`, for the component to consume typed.

- [ ] **Step 1: Regenerate the backend OpenAPI** — run the project's export (e.g. `cd /e/investintell-light/backend && .venv/Scripts/python scripts/export_openapi.py` if it exists; otherwise start the app and dump `/openapi.json` to `backend/openapi.json` per the project's documented flow). Confirm `MacroQuadrantOut`/`macro_quadrant` appear in `backend/openapi.json`.

- [ ] **Step 2: Regenerate frontend types** — `cd /e/investintell-light/frontend && pnpm run types`. Confirm `macro_quadrant` is present in `src/lib/api/api.d.ts`.

- [ ] **Step 3: Export the type** — add `export type MacroQuadrant = NonNullable<MacroRegime["macro_quadrant"]>;` in `client.ts` near the `MacroRegime` export.

- [ ] **Step 4: Verify typecheck**

Run: `cd /e/investintell-light/frontend && pnpm run typecheck`
Expected: PASS (no type errors from the new field).

- [ ] **Step 5: Commit**

```bash
git add backend/openapi.json frontend/src/lib/api/api.d.ts frontend/src/lib/api/client.ts
git commit -m "Regenerate types for macro_quadrant; export MacroQuadrant"
```

---

### Task 3: Per-class bands chart builder

**Files:**
- Create: `frontend/src/lib/charts/hc/macro-bands.ts`
- Test: `frontend/src/lib/charts/hc/macro-bands.test.ts`

**Interfaces:**
- Consumes: `ChartColors` (`chartColors()`), the `bands` array.
- Produces: `export function buildHcMacroBandsOption(bands: { asset_class: string; min_weight: number; max_weight: number }[], colors: ChartColors): Options | null` — a horizontal `columnrange` (one row per class showing `[min,max]`; mirror `buildHcDriftBandsOption`, `rebalance.ts:52`). `null` when `bands` is empty. Categories ordered `equity, fixed_income, alternatives, cash`. Token colors only.

- [ ] **Step 1: Write the failing test** (vitest, pure builder — no jsdom):

```ts
import { describe, it, expect } from "vitest";
import { buildHcMacroBandsOption } from "./macro-bands";
import { TEST_COLORS } from "./__fixtures__/colors";

describe("buildHcMacroBandsOption", () => {
  it("returns null for empty bands", () => {
    expect(buildHcMacroBandsOption([], TEST_COLORS)).toBeNull();
  });

  it("emits one range per class with min/max extent", () => {
    const opt = buildHcMacroBandsOption(
      [
        { asset_class: "equity", min_weight: 0.4, max_weight: 0.64 },
        { asset_class: "cash", min_weight: 0.03, max_weight: 0.105 },
      ],
      TEST_COLORS,
    )!;
    const data = (opt.series?.[0] as any).data;
    expect(data).toHaveLength(2);
    expect(data[0]).toEqual(expect.arrayContaining([0.4, 0.64]));
  });

  it("orders classes equity, fixed_income, alternatives, cash", () => {
    const opt = buildHcMacroBandsOption(
      [
        { asset_class: "cash", min_weight: 0, max_weight: 0.1 },
        { asset_class: "equity", min_weight: 0.4, max_weight: 0.6 },
      ],
      TEST_COLORS,
    )!;
    const cats = (opt.xAxis as any).categories;
    expect(cats.indexOf("equity")).toBeLessThan(cats.indexOf("cash"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-light/frontend && pnpm test src/lib/charts/hc/macro-bands.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `buildHcMacroBandsOption` (horizontal `columnrange`; canonical class ordering; token colors).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /e/investintell-light/frontend && pnpm test src/lib/charts/hc/macro-bands.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/charts/hc/macro-bands.ts frontend/src/lib/charts/hc/macro-bands.test.ts
git commit -m "Add macro per-class bands chart builder"
```

---

### Task 4: Render gate + quadrant + bands in `MacroRegimeView`

**Files:**
- Modify: `frontend/src/components/macro/MacroRegimeView.tsx`
- Test: `frontend/src/components/macro/MacroRegimeView.quadrant.test.tsx` (NEW — there is currently NO test file for this component)

**Interfaces:**
- Consumes: `MacroRegime.macro_quadrant` (Task 2), `buildHcMacroBandsOption` (Task 3), `HighchartsChart` (`frontend/src/components/charts/HighchartsChart.tsx`).
- Produces: a new section in `MacroRegimeView` that, when `macro_quadrant` is present, shows: the live GATE state (risk_on/risk_off) + trend/credit/drawdown vote chips + dwell_days, the current quadrant label (RECOVERY/EXPANSION/SLOWDOWN/CONTRACTION, or "n/a" when null), the growth/inflation states/scores, the `combined_regime` label, and `<HighchartsChart options={buildHcMacroBandsOption(macro_quadrant.bands, colors)} />` (or the `haven_tilt` list when STAG_GOLD). When `macro_quadrant` is absent, a discreet empty-state.

**Required investigation (implementer):** read `MacroRegimeView.tsx` to see how it obtains `colors` (VERIFIED: `chartColors()` in a `useEffect` post-mount, stored in state, lines ~173-216) and how it composes the existing blocks (the RRG via `buildHcMacroRrgOption` in an `h-[440px]` container). Insert the new section near the RRG for cohesion. Do NOT modify `buildHcMacroRrgOption` (the RRG stays; the new section is complementary). Reuse the existing `StateBadge`/`VoteChip` sub-components if suitable.

- [ ] **Step 1: Write the failing test** (jsdom; mock `fetchMacroRegime`):

```tsx
// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";

vi.mock("@/lib/api/client", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/client")>()),
  fetchMacroRegime: vi.fn().mockResolvedValue({
    detector: "vote2of3", state: "risk_on", vote_count: 1,
    votes: { credit: false, trend: true, nfci: false },
    as_of: "2026-06-18", days_in_state: 10, last_flip: null,
    signal: { ratio: 1, p20_5y: 0.9, distance_pct: 5, nfci: -0.2 },
    recent_flips: [], history: [],
    macro_quadrant: {
      as_of: "2026-06-18", quadrant: "EXPANSION",
      growth_state: "up", inflation_state: "up",
      growth_score: 0.07, inflation_score: 0.02,
      combined_regime: "INFLATION",
      bands: [
        { asset_class: "equity", min_weight: 0.3, max_weight: 0.54 },
        { asset_class: "fixed_income", min_weight: 0.16, max_weight: 0.34 },
        { asset_class: "alternatives", min_weight: 0.13, max_weight: 0.31 },
        { asset_class: "cash", min_weight: 0.05, max_weight: 0.17 },
      ],
      haven_tilt: null,
      gate: { as_of: "2026-06-18", state: "risk_on", trend_vote: true,
              credit_vote: false, drawdown_vote: false, vote_count: 1, dwell_days: 40 },
    },
  }),
}));

import MacroRegimeView from "./MacroRegimeView";

it("shows current quadrant and combined regime", async () => {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <MacroRegimeView />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText(/EXPANSION/i)).toBeInTheDocument());
  expect(screen.getByText(/INFLATION/i)).toBeInTheDocument();
});
```

(Match the import style/default-vs-named export and any required props of `MacroRegimeView` to the real component — read it first. If it expects props, pass minimal stubs.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-light/frontend && pnpm test src/components/macro/MacroRegimeView.quadrant.test.tsx`
Expected: FAIL (no "EXPANSION"/"INFLATION" text rendered).

- [ ] **Step 3: Implement** the new section (gate chips + quadrant + scores + combined regime + bands chart / haven tilt; empty-state when absent).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /e/investintell-light/frontend && pnpm test src/components/macro/MacroRegimeView.quadrant.test.tsx` then `pnpm run typecheck`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/macro/MacroRegimeView.tsx frontend/src/components/macro/MacroRegimeView.quadrant.test.tsx
git commit -m "Show live gate, quadrant, and regime bands on the Macro page"
```

---

### Task 5: Verification gate

- [ ] **Step 1: Backend** `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest -q` → green (or only documented pre-existing failures); `ruff check app/` + `mypy app/` clean on `schemas/macro.py` + `routes/macro.py`.
- [ ] **Step 2: Frontend** `cd /e/investintell-light/frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm build` → all green.
- [ ] **Step 3:** Commit any gate fixups.

## Verification gate (the green bar)

- Backend: `.venv/Scripts/python -m pytest -q` green; `ruff check app/` + `mypy app/` clean on the touched files.
- Frontend: `pnpm test` green; `pnpm run typecheck` clean; `pnpm run lint` clean; `pnpm build` succeeds.

## Self-Review (assumptions, risks, spec gaps)

**Coverage of spec §3.4 / §7.4:**
- New `macro_quadrant` block (gate + combined regime + bands + haven tilt) on `/macro/regime` → Task 1.
- Types regenerated + `MacroQuadrant` export → Task 2.
- Per-class bands chart builder → Task 3.
- Render gate + quadrant + bands in `MacroRegimeView` → Task 4.
- Composite stays the headline detector (O3); only 4 classes shown (O5) → Global Constraints / Tasks 1, 3.
- `pnpm run types` sequenced after the backend change → Task 2 (explicit ordering).

**Assumptions.**
- The composite read and the route's 404 behavior are unchanged; the gate block is purely additive and degrades to `gate=None` / `quadrant=None` when unmaterialized. This makes the page robust before the gate worker has backfilled.
- `MacroRegimeView` builds `colors` post-mount via `chartColors()` (VERIFIED), so the bands chart follows the same pattern as the RRG.
- The bands chart reuses the `columnrange` pattern from `buildHcDriftBandsOption` (VERIFIED location/signature).

**Risks / what could go wrong.**
- **Quadrant is live once the worker backfills (decision A)** — read from `regime_gate_daily`, not a deferred proxy pipeline. The quadrant tile reads "n/a" ONLY before the Sprint-1 worker's first run (the gate row has no quadrant yet); after that it shows the real quadrant + the SLOWDOWN→goldfix tilt. The only residual coupling is that the reader and the worker DDL must agree on the quadrant column/lowercase values (Sprint 1 Task 2 ↔ Sprint 2 Task 7).
- **Type regen ordering:** if `pnpm run types` runs before the backend schema change is committed/exported, `api.d.ts` won't contain `macro_quadrant` and Tasks 3–4 won't typecheck. Task 2 enforces the order; the implementer must regenerate `backend/openapi.json` first.
- **No existing component test:** `MacroRegimeView` has NO test file today (VERIFIED). Task 5's jsdom test is the first — the implementer must wire the `QueryClientProvider` + mock exactly as the component fetches (default vs named export, any required props). Budget time to get the harness right.

**Spec gaps / ambiguities / errors found (bias-check payoff).**
- **ERROR in the spec's framing (already flagged by the spec itself, confirmed here): `MacroRegimeResponse` had NO growth/inflation/quadrant/gate fields.** VERIFIED `macro.py:39-57` exposes only the vote2of3 detector (`detector, state, vote_count, votes{credit,trend,nfci}, signal, recent_flips, history`). This sprint ADDS the entire `macro_quadrant` block — correctly treated as new.
- **RESOLVED (decision A, spec §9) — the quadrant source.** The carried-over gap is settled: the `regime_gate` worker fetches SPY/HYG/IEF/TIP and materializes `growth_score`/`inflation_score`/`quadrant` into `regime_gate_daily`; this route READS them via `fetch_gate_regime` (no backend TIP/IEF — verified not in `eod_prices`; no synchronous-Tiingo call in the request path). This is the single source of truth shared with the builder (Sprint 3), and it simplifies both Sprints 3+4 (one DB read instead of a proxy pipeline) while keeping the SLOWDOWN→goldfix tilt live. `macro_quadrant_from_proxies` is NOT wired into the route.
- **MINOR — `haven_tilt` in the route is the conviction target, not the realized tilt.** When SLOWDOWN, the route returns the full goldfix target (the available-names filtering happens in the builder against a real universe). The page should label it "target tilt" to avoid implying it's the realized allocation. Documented in Task 1.
- **MINOR — line drift.** Route handler verified at `macro.py:42-97`; `fetchMacroRegime` at `client.ts:1424`; `MacroRegime` at `client.ts:290-291`; `buildHcDriftBandsOption` at `rebalance.ts:52`. All match the spec; use these anchors.
