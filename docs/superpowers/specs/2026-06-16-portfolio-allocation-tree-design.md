# Portfolio Allocation tree (Asset Class → Strategy → Holding) — Design

**Goal:** Add a read-only **Allocation** section to the portfolio page that renders the portfolio's holdings as a 3-level Highcharts Grid Pro tree (Asset Class → Strategy → Holding), mirroring the builder's grouped results output. The existing editable holdings grid is left untouched.

**Approved decisions (brainstorming):**
- **Where:** a new, separate read-only "Allocation" section on the portfolio page; the editable holdings grid (cost/shares/remove) stays as-is.
- **Hierarchy:** Asset Class → Strategy → Holding (mirror the builder). Funds group by `strategy_label`; equities (no strategy) fall under **"Direct equity"** within their class.
- **Cash:** a top-level node sibling to the asset classes; weights are over the **total** portfolio value (incl. cash), so the tree sums to 100%.
- **Approach A:** extend the existing overview contract with per-position taxonomy and **reuse** the builder's grid adapter (`weightsTreeGridOptions`) + `DataGrid` unchanged; a new pure transform builds the tree rows.

---

## Architecture & data flow

The portfolio page already fetches the overview (`GET /portfolios/{id}/overview`), which returns `positions: PositionOverview[]` plus `aggregates` (carrying `total_market_value` and `total_value`). This design:

1. **Backend** enriches each `PositionOverview` with `asset_class`, `strategy_label`, `instrument_id` (None for direct equities / non-fund tickers). The overview route resolves taxonomy using the existing `_fund_instrument_by_ticker` resolver + the `load_fund_asset_class` / `load_fund_strategy_label` loaders (added in the broad-universe work), and passes a `taxonomy_by_ticker` map into `build_overview` (mirroring how `names_by_ticker` is passed today).
2. **Frontend** maps the enriched positions to `WeightTreeRow[]` via a new pure transform `buildAllocationTree(positions, totalValue)`, then renders them with the **unchanged** `weightsTreeGridOptions(...)` + `DataGrid`.

No new endpoint, no extra round-trip: the Allocation section consumes the same overview payload the page already loads. Cash needs no new field — it is derived as `total_value − total_market_value`.

```
GET /portfolios/{id}/overview
  route resolves taxonomy_by_ticker (ticker → {asset_class, strategy_label, instrument_id})
  build_overview(positions, closes, names, taxonomy_by_ticker, cash)
    → PositionOverview[] (now incl. asset_class / strategy_label / instrument_id) + aggregates
  ↓ (existing react-query fetch)
PortfolioOverviewView
  buildAllocationTree(overview.positions, overview.aggregates.total_value) → WeightTreeRow[]
  <DataGrid options={weightsTreeGridOptions(rows)} />   ← reused from the builder
```

---

## Backend changes

**Contract — `PositionOverview` (additive):**
```python
asset_class: str | None = None
strategy_label: str | None = None
instrument_id: uuid.UUID | None = None
```
None for direct equities and any ticker that does not resolve to a fund instrument.

**`build_overview` signature:** add a `taxonomy_by_ticker: Mapping[str, PositionTaxonomy] | None = None` parameter (mirroring `names_by_ticker`), where `PositionTaxonomy` is a small typed tuple/dataclass `(asset_class, strategy_label, instrument_id)`. The parameter **defaults to None/empty** so existing callers — including `tests/test_portfolios_overview.py` which calls `build_overview` directly — keep working with all-None taxonomy. Populate the three new fields per row from this map (all-None when the ticker is absent).

**Overview route (`app/api/routes/portfolios.py`, ~line 290):** before calling `build_overview`, resolve the taxonomy map:
- `instrument_by_ticker = await _fund_instrument_by_ticker(session, tickers)` (existing helper; covers `Fund.ticker` and `FundClass.ticker` → series → instrument).
- `asset_class_of = await load_fund_asset_class(session, list(instrument_by_ticker.values()))`
- `strategy_of = await load_fund_strategy_label(session, list(instrument_by_ticker.values()))`
- For each position ticker:
  - If it resolves to a fund instrument → `(asset_class_of[iid], strategy_of[iid], iid)`.
  - Else (direct equity / unresolved) → `("equity", None, None)`. Rationale: a portfolio holding that is not a fund is a directly-held equity; classing it as `equity` keeps it in the tree under a sensible top-level node, with the strategy falling back to "Direct equity" on the frontend.

**Equity asset_class caveat:** non-fund tickers are assumed to be direct equities (`asset_class="equity"`). There is no per-equity asset-class lookup in scope; if a non-equity non-fund ticker ever appears, it still renders (under "Equity" → "Direct equity"). This is acceptable for the current portfolio model and is called out as a known simplification.

**Regen** `backend/openapi.json` + `frontend/src/lib/api/api.d.ts`.

---

## Frontend — pure transform `buildAllocationTree`

New file `frontend/src/lib/portfolio/allocationTree.ts`. Reuses the **output contract** of the builder (`WeightTreeRow` from `@/lib/builder/weightsTree`) so the grid adapter is reused verbatim.

**Input:** an `AllocationInput[]` (decoupled from the API type) `{ ticker, name, marketValue, assetClass, strategyLabel, instrumentId }`, plus `totalValue: number` and `cashValue: number`.

**Output:** `WeightTreeRow[]` (id / parentId / label / weight / instrumentId), same shape consumed by `weightsTreeGridOptions`.

**Rules:**
- Per-holding weight = `marketValue / totalValue` (guard `totalValue > 0`; if 0, return `[]`).
- Group Asset Class → Strategy → Holding; aggregate parent weights from children; order asset classes, strategies, and holdings by descending weight (same logic the builder's `buildWeightsTree` uses — extract a shared grouping core if duplication is material, otherwise duplicate the ~40 lines to keep the builder untouched).
- **Asset-class label:** reuse the `equity/fixed_income/cash/alternatives` label map; unknown → titled code; null → "Other".
- **Strategy fallback:** `strategyLabel ?? (instrumentId ? "Unclassified" : "Direct equity")` — funds without a strategy stay "Unclassified"; non-fund holdings (no instrumentId) read "Direct equity".
- **Cash node:** if `cashValue > 0`, prepend a top-level row `{ id: "ac:__cash__", parentId: null, label: "Cash", weight: cashValue/totalValue, instrumentId: null }` with **no children**. It is ordered among the asset-class roots by its weight.
- **Leaf instrumentId:** funds carry `instrumentId` (→ dossier link via the existing `weightLabelFormatter`); equities carry `null` (rendered as plain text).
- Drop holdings with weight ≤ `1e-6` (solver/rounding noise floor).

**Unit identity:** the transform is pure (no React/DOM/network), fully unit-testable, and depends only on `WeightTreeRow` + a small label map.

---

## Frontend — UI section

New component `frontend/src/components/portfolio/PortfolioAllocationSection.tsx`:
- Props: the overview `positions`, `totalValue`, `cashValue` (or the whole overview object).
- Builds rows via `buildAllocationTree(...)` and renders `<DataGrid options={weightsTreeGridOptions(rows)} className="h-[420px] w-full" emptyMessage="No holdings to allocate." />`.
- Wrapped in the standard card/section styling used elsewhere on the page (matches `SelectionDiagnostics`/results section conventions).

Rendered inside `PortfolioOverviewView`, **below** the existing editable holdings `DataGrid` (which is unchanged). The section only appears when there is at least one priced position (or cash > 0).

---

## Error handling & edge cases

- **Empty / unpriced portfolio:** `total_value === 0` → transform returns `[]` → `emptyMessage` shown.
- **All-cash portfolio:** only the "Cash" top-level node renders.
- **Fund with null asset_class:** groups under "Other" (existing builder behavior).
- **Ticker resolving to multiple instruments:** `_fund_instrument_by_ticker` already deterministically picks the lowest instrument_id (existing behavior); no change.
- **Backend taxonomy load failure:** the loaders are read-only `SELECT`s; a failure surfaces as a 500 from the overview route (fail-loud, consistent with the rest of the route). No silent fallback that would mis-class holdings.

---

## Testing (TDD)

**Frontend — `allocationTree.test.ts`:**
- Cash node appears at top level with the correct weight; no children.
- Equity holding (null strategy, null instrumentId) → strategy label "Direct equity"; leaf has `instrumentId: null`.
- Fund holding → strategy = its `strategy_label`; leaf carries `instrumentId` (→ link).
- Parent weights aggregate; asset classes ordered by descending weight; cash ordered among roots by weight.
- Zero/sub-floor weights dropped; `totalValue === 0` → `[]`.

**Frontend — grid adapter:** already covered by `weightsTreeGridOptions.test.ts` (reused unchanged); no new grid test required. A light render smoke test of `PortfolioAllocationSection` (jsdom, mocked `DataGrid`) asserting it builds rows and renders the grid is optional but recommended.

**Backend — overview route test:** with stubbed taxonomy loaders + `_fund_instrument_by_ticker`, assert each `PositionOverview` carries the expected `asset_class` / `strategy_label` / `instrument_id` for a fund ticker vs. a direct-equity ticker (the latter → `("equity", None, None)`). Confirm no regression to existing overview fields/aggregates.

**Gate:** frontend typecheck (no new errors in touched files — the repo carries pre-existing errors in `rebalance.test.ts`); backend `pytest` for the portfolio overview + builder taxonomy suites; `ruff` clean on touched backend files.

---

## File structure

| File | Type | Responsibility |
|---|---|---|
| `backend/app/schemas/portfolios.py` | Modify | `PositionOverview` += `asset_class` / `strategy_label` / `instrument_id`. |
| `backend/app/services/portfolio_crud.py` | Modify | `build_overview` accepts `taxonomy_by_ticker`; populates the new fields. |
| `backend/app/api/routes/portfolios.py` | Modify | Resolve taxonomy map (existing resolver + loaders), pass into `build_overview`. |
| `backend/tests/test_portfolios_overview.py` | Modify | Assert per-position taxonomy (fund vs equity); existing direct `build_overview` call keeps working via the defaulted param. |
| `backend/openapi.json` + `frontend/src/lib/api/api.d.ts` | Modify (generated) | Regen with the new `PositionOverview` fields. |
| `frontend/src/lib/portfolio/allocationTree.ts` | Create | Pure `buildAllocationTree` (cash node, equity fallback, aggregation). |
| `frontend/src/lib/portfolio/allocationTree.test.ts` | Create | Unit tests for the transform. |
| `frontend/src/components/portfolio/PortfolioAllocationSection.tsx` | Create | Read-only Allocation tree section (reuses `weightsTreeGridOptions` + `DataGrid`). |
| `frontend/src/components/portfolio/PortfolioOverviewView.tsx` | Modify | Render `<PortfolioAllocationSection>` below the editable holdings grid. |

---

## Out of scope / notes

- **No change to the editable holdings grid** (positions table, cost/shares/remove, live "last" updates).
- **No per-equity asset-class enrichment** beyond the `equity` default for non-fund tickers (called out above).
- **Reuse over duplication:** `weightsTreeGridOptions`, `weightLabelFormatter`, `DataGrid`, and `WeightTreeRow` are reused unchanged. The grouping logic is shared in spirit with `buildWeightsTree`; extract a shared core only if the duplication proves material during implementation.
