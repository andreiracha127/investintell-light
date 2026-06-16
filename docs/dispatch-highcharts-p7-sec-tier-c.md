# Dispatch - Highcharts Migration P7 SEC Tier C

**Date:** 2026-06-15  
**Primary repo:** `E:\investintell-light`  
**Worker repo:** `E:\investintell-datalake-workers`  
**Current light branch at dispatch creation:** `feat/highcharts-p6-cache-ssr`  
**Purpose:** implement P7 from the Highcharts/fund dossier migration: SEC 13F + Form 4 ingestion, Tier C tables, Light endpoints, and the dossier panels that were empty until P7.

## Current Baseline

P6 is considered complete by the owner. At dispatch creation time the relevant recent commits in `E:\investintell-light` were:

- `d862361 feat(funds): add cached dossier route handlers`
- `ea30bd9 feat(funds): hydrate dossier queries on first paint`

P7 is not implemented in the live Light code yet:

- `backend/app/services/fund_dossier_tier_b.py` still returns `insider_data=None`.
- `backend/app/schemas/fund_analysis.py` still types `insider_data` as `None`.
- There are no Light endpoints for:
  - `GET /funds/{id}/institutional-reveal`
  - `GET /holdings/{cusip}/reverse-lookup`
- There are no frontend fetchers/panels wired to populated Tier C data.

The worker repo exists at `E:\investintell-datalake-workers`. It already documents SEC ingestion plans in `docs/INGESTION_DESIGN.md`, including `sec_13f_ingestion` and `form345_ingestion`, but no production worker for P7 was confirmed in this dispatch pass.

## Preserve Dirty Work

Before editing any repo, run:

```powershell
git -C E:\investintell-light status --short --branch
git -C E:\investintell-datalake-workers status --short --branch
```

At dispatch creation time, `E:\investintell-light` had these unrelated untracked files. Do not stage, remove, reformat, or normalize them unless the owner explicitly authorizes it:

- `.idea/AugmentWebviewStateStore.xml`
- `backend/_gate_vs_full_backtest.py`
- `backend/_navdata.csv`
- `backend/_navdata.err`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

At dispatch creation time, `E:\investintell-datalake-workers` was also dirty:

- modified: `.gitignore`
- modified: `railway.toml`
- modified: `src/workers/characteristics.py`
- untracked: `.ai/`, `.playwright-mcp/`, `AGENTS.md`, `design/`, and several smoke screenshots.

Treat those worker-repo changes as owner/other-session work. Work around them without reverting.

## Read First

In `E:\investintell-light`:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/dispatch-highcharts-p5-tier-b-dossier.md`
4. `docs/dispatch-highcharts-p6-cache-ssr.md`
5. `backend/app/api/routes/funds.py`
6. `backend/app/services/fund_dossier_tier_b.py`
7. `backend/app/schemas/fund_analysis.py`
8. `frontend/src/components/funds/FundProfileView.tsx`
9. `frontend/src/lib/funds/dossierQueries.ts`
10. `frontend/src/lib/funds/dossierServer.ts`

In `E:\investintell-datalake-workers`:

1. `AGENTS.md` if present
2. `README.md` or equivalent root docs
3. `docs/INGESTION_DESIGN.md`
4. `src/db.py`
5. `src/run.py`
6. `src/run_worker.py`
7. `src/workers/nport_lookthrough.py`
8. one simple ingestion worker such as `src/workers/treasury_ingestion.py`
9. `tests/test_nport_lookthrough.py`
10. `schemas/nport_lookthrough.sql`

Use repo truth over this dispatch if the code has moved. Record drift before edits.

## Required Opening Verification

Run from `E:\investintell-light`:

```powershell
rg -n "P7|Tier C|13F|Form 4|institutional-reveal|reverse-lookup|insider|sec_13f|sec_insider" docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md
rg -n "institutional-reveal|reverse-lookup|insider_data|sec_13f|sec_insider|curated_institutions|sec_managers" backend/app frontend/src backend/openapi.json frontend/src/lib/api/api.d.ts
rg -n "unstable_cache|HydrationBoundary|dossierQueries|dossierServer|Cache-Control" frontend/src/app frontend/src/lib/funds
```

Run from `E:\investintell-datalake-workers`:

```powershell
rg -n "sec_13f_ingestion|form345_ingestion|13F|Form 4|sec_13f_holdings|sec_insider|sec_managers|curated_institutions|900_305|900_306" docs src schemas tests railway.toml
rg --files src/workers schemas tests | rg "13f|form345|insider|adv|manager"
```

Expected:

- P6 cache/hydration files exist in Light.
- Tier C Light endpoints are absent or incomplete.
- Worker repo has conventions for worker modules, schema files, tests, advisory locks, and Railway service wiring.
- Existing worker-repo dirty files are preserved.

## P7 Scope

Implement P7 only:

- SEC 13F ingestion in `E:\investintell-datalake-workers`.
- Form 4/Form 345 insider ingestion in `E:\investintell-datalake-workers`.
- Tier C tables and/or materialized outputs needed by Light.
- Light backend endpoints:
  - `GET /funds/{instrument_id}/institutional-reveal`
  - `GET /holdings/{cusip}/reverse-lookup`
  - populated `insider_data` in `GET /funds/{instrument_id}/entity-analytics`
- Light frontend:
  - Deep Analysis insider section populated when data exists.
  - Relationships modal/panels for holder network and institutional overlap.
  - Empty states remain explicit when SEC Tier C data is unavailable.
- P6 cache/proxy extension for the new public Tier C GET endpoints if they are exposed in the dossier.

## P7 Non-Scope

- No P8 cleanup of ECharts/ixchart.
- No broad redesign of the fund dossier.
- No deploy unless explicitly requested.
- No PR unless explicitly requested.
- No destructive production SQL.
- No scraping beyond SEC/EDGAR/Form 345 sources required for P7.
- No silent fake values for missing institutional or insider data.
- No caching of user-specific portfolio data.

## Workstream A - Worker Repo SEC 13F

### A1. Schema

Add idempotent schema SQL in `E:\investintell-datalake-workers\schemas`.

Expected tables/views, adjusted to live repo conventions:

- `sec_13f_holdings`
  - `cik`
  - `manager_name` or manager FK if `sec_managers` exists
  - `period`
  - `report_date` if distinct from period
  - `cusip`
  - `name`
  - `value`
  - `shares`
  - accession/source metadata
  - fetched/updated timestamps
- `sec_13f_diffs` if the worker computes changes between the latest two periods.
- `sec_managers` and/or `curated_institutions` if not already present.

The high-level spec names `sec_13f_holdings`, `curated_institutions`, and `sec_managers`. `docs/INGESTION_DESIGN.md` also mentions `sec_13f_diffs` and advisory lock `900_305`. Reconcile the names with live schema before coding.

Use conflict keys that make reruns idempotent. Preserve source identifiers so parser bugs can be traced.

### A2. Worker

Add a worker module, expected name:

- `src/workers/sec_13f_ingestion.py`

Responsibilities:

- parse SEC EDGAR `13F-HR` information tables
- write `sec_13f_holdings`
- seed or read managers from `sec_managers` / `curated_institutions`
- support bounded per-run limits
- be resumable and idempotent
- use advisory lock `900_305` unless live registry says otherwise
- follow the repo's worker contract: `run(dsn, ...) -> dict`

If the repo already requires `sec_adv_ingestion` before 13F, either implement the minimal manager seed needed for P7 or stop and report that `sec_adv_ingestion` is a prerequisite.

### A3. Tests

Add tests with local fixtures:

- parser test for a tiny 13F information table fixture
- schema/upsert idempotency test where feasible
- advisory lock id registry test
- no-live-network test by default

Do not make unit tests depend on SEC network availability.

## Workstream B - Worker Repo Form 4 / Form 345

### B1. Schema

Add schema for raw and aggregate insider data. The Light spec names `sec_insider_sentiment`; the worker design may prefer a raw `sec_insider_transactions` table from Form 345 bulk ZIP. A safe shape is:

- raw: `sec_insider_transactions`
  - accession/source keys
  - issuer CIK
  - reporting owner CIK/name
  - transaction date
  - transaction code
  - shares
  - value
  - buy/sell classification
- aggregate: `sec_insider_sentiment`
  - `cik`
  - `quarter`
  - `buy_value`
  - `sell_value`
  - optional counts and net value
  - updated timestamp

If the existing repo convention already has one of these, extend rather than duplicate.

### B2. Worker

Add a worker module, expected name from worker docs:

- `src/workers/form345_ingestion.py`

The Light spec calls it `insider_ingestion`; if the worker repo uses `form345_ingestion`, keep the worker-repo name and document the mapping:

- P7 `insider_ingestion` product capability = worker `form345_ingestion`

Responsibilities:

- parse SEC Form 345/Form 4 bulk structured data
- populate raw transactions
- aggregate to `sec_insider_sentiment`
- use advisory lock `900_306` unless live registry says otherwise
- support quarterly full-file reruns with conflict-key idempotency

### B3. Tests

Add tests with local Form 345 fixtures:

- parse `SUBMISSION`, `REPORTINGOWNER`, and transaction rows if using ZIP/TSV source
- classify buys/sells deterministically
- aggregate quarterly `buy_value` and `sell_value`
- verify rerun idempotency

## Workstream C - Light Backend Tier C

### C1. Schemas

Extend `backend/app/schemas/fund_analysis.py` or add a focused Tier C schema module.

Required response families:

- `FundInstitutionalRevealResponse`
  - fund identity
  - report/period metadata
  - top institutional holders of the fund's underlying holdings
  - institutional overlap by CUSIP/security
  - holder network nodes/edges for the Relationships modal
  - explicit empty-state reason when 13F data is unavailable
- `HoldingReverseLookupResponse`
  - requested CUSIP/security
  - institutions holding it
  - funds/series exposing it where available
  - value/shares/period metadata
  - explicit empty-state reason when unavailable
- `InsiderData`
  - issuer/fund mapping metadata
  - quarterly buy/sell/net values
  - sentiment gauge fields used by frontend
  - source/as-of metadata

Keep response models typed with Pydantic v2. Do not return untyped dicts from routes.

### C2. Services

Add service functions near the existing fund dossier service layer.

Expected joins:

- resolve fund -> latest/top holdings from P4/P5 sources
- holdings CUSIP -> `sec_13f_holdings`
- CUSIP -> institutions/managers
- issuer/fund identity -> `sec_insider_sentiment`

Use empty-state payloads for missing SEC tables or no matching CUSIPs, but do not hide real SQL errors as "no data" unless the relation absence is an expected deployment gap and tests cover it.

### C3. Routes

Add routes in `backend/app/api/routes/funds.py` or a focused router if the file is too large:

```text
GET /funds/{instrument_id}/institutional-reveal
GET /holdings/{cusip}/reverse-lookup
```

Update existing `GET /funds/{instrument_id}/entity-analytics` so `insider_data` is populated when source data exists.

Regenerate:

- `backend/openapi.json`
- `frontend/src/lib/api/api.d.ts`

Add typed client fetchers in `frontend/src/lib/api/client.ts`.

### C4. Backend Tests

Add tests for:

- institutional reveal success
- institutional reveal empty state
- reverse lookup success
- reverse lookup empty state
- entity analytics with populated `insider_data`
- missing fund / invalid CUSIP
- source table absent where expected by deployment guard

Prefer fake sessions/fixtures where current backend test patterns allow it.

## Workstream D - Light Frontend Tier C Panels

### D1. Client/query layer

Update:

- `frontend/src/lib/api/client.ts`
- `frontend/src/lib/funds/dossierQueries.ts`
- `frontend/src/lib/funds/dossierServer.ts`
- `frontend/src/app/api/funds/[id]/[sub]/route.ts` or equivalent P6 proxy layer

Add:

- `fetchFundInstitutionalReveal`
- `fetchHoldingReverseLookup`
- query keys for institutional reveal and reverse lookup
- cached route handling for new public Tier C GET endpoints

Keep query keys stable and params normalized.

### D2. Deep Analysis insider section

Update `frontend/src/components/funds/FundProfileView.tsx` and related chart builders/tests:

- replace the P5 insider empty-state with populated `insider_data` when present
- show buy/sell/net values and a compact sentiment gauge
- preserve explicit empty-state when `insider_data` is null or source data is unavailable

### D3. Relationships modal/panels

Implement the P7 relationship surfaces from the spec:

- holder network
- institutional overlap circular/relationship view
- ranked institutional holder bars/table

Use existing Highcharts wrappers/builders where practical. If a force/network module is needed, verify the installed Highcharts module first and add pure builder tests. If the module is unavailable or too brittle, implement a clear ranked-bar/table fallback and document the tradeoff.

Do not make this a marketing-style modal. It should remain dense, analytical, and consistent with the Cockpit/Graphite UI.

### D4. Empty/loading/error states

Every Tier C panel needs:

- loading state
- backend-detail error state
- explicit empty-state with reason
- no fake metrics

## Workstream E - P6 Cache/Hydration Integration

The new Tier C GET endpoints are public/catalog-like and can use the P6 cache layer if they do not require user-specific auth.

Update P6 route handlers/query definitions only for:

- institutional reveal
- reverse lookup if consumed in the dossier
- entity analytics if cache keys need to reflect insider data freshness

Use tags:

- `fund:{id}`
- `fund:{id}:institutional-reveal`
- `holding:{cusip}:reverse-lookup`
- `fund:{id}:entity-analytics`

Use conservative TTLs until freshness is proven:

- 13F institutional data: long TTL is acceptable after ingestion; start with 3600s.
- insider sentiment: shorter TTL if updated daily/weekly; start with 3600s unless product needs fresher.

If ingestion jobs can trigger invalidation, wire `revalidateTag` through the existing safe server-side invalidation pattern. Do not create a public unauthenticated invalidation endpoint.

## Validation Gates

Worker repo:

```powershell
cd E:\investintell-datalake-workers
python -m pytest tests/test_sec_13f_ingestion.py tests/test_form345_ingestion.py -q
python -m pytest tests -q
```

If the full worker suite has known unrelated failures, run targeted tests plus import smoke and report exact skipped failures.

Light backend:

```powershell
cd E:\investintell-light\backend
python -m pytest tests -q
```

Light frontend:

```powershell
cd E:\investintell-light\frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Browser:

- start backend/frontend on free ports
- open a real fund dossier
- open Deep Analysis and verify insider section:
  - populated when fixture/live data exists
  - explicit empty-state when no data exists
- open Relationships and verify:
  - holder network or fallback
  - institutional overlap
  - ranked holder view
- verify network calls hit the intended Light endpoints/proxy routes
- verify no blank charts and no overlapping text at desktop/mobile widths
- verify P6 cache headers still exist for proxied Tier C routes

## Commit Discipline

This is a multi-repo dispatch. Keep commits separate by repo.

Suggested worker-repo commits:

```powershell
git commit -m "feat(sec): add 13F ingestion worker"
git commit -m "feat(sec): add Form 345 insider ingestion"
```

Suggested Light commits:

```powershell
git commit -m "feat(funds): add Tier C institutional endpoints"
git commit -m "feat(funds): wire Tier C dossier relationships"
```

Before every commit:

```powershell
git status --short
git diff --stat
git diff --cached --name-only
```

Do not stage unrelated dirty files from either repo.

## Stop Conditions

Stop and report instead of guessing if:

- SEC source contract or fair-access requirements are unclear.
- worker repo dirty files overlap with required P7 files and cannot be safely isolated.
- `sec_managers` / `curated_institutions` prerequisites are missing and require a broader `sec_adv_ingestion` phase.
- target DB role cannot create the Tier C tables or hypertables.
- CUSIP/entity identity mapping is insufficient to connect fund holdings to 13F/insider data.
- P6 cache layer has moved and route/proxy integration is unclear.
- tests require live SEC network access rather than local fixtures.

## Final Report Shape

Report in Portuguese:

1. Branches and final HEAD SHA(s) for both repos.
2. Worker modules/tables added.
3. Light endpoints and schemas added.
4. Frontend panels/modal sections wired.
5. Exact gates run and results.
6. Browser evidence: fund route, panels opened, endpoint calls, cache headers.
7. Any skipped gates, missing SEC/data prerequisites, or unrelated dirty files preserved.

Do not deploy, push, or open PR unless the owner explicitly asks.
