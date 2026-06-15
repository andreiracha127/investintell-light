# Dispatch — Highcharts Migration P6 Cache + SSR Hydration

**Date:** 2026-06-15  
**Repo:** `E:\investintell-light`  
**Branch:** current checkout is expected to be `main`. Verify before work.  
**Purpose:** implement P6 from the Highcharts/fund dossier migration: frontend route-handler caching plus SSR React Query hydration for the fund dossier.

## Current Baseline

At dispatch creation time, current recent commits were:

- `fc07910 feat(funds): add Tier B dossier analytics endpoints`
- `02e9394 feat(funds): wire Tier B dossier tabs and deep analysis`

The fund dossier now has P4/P5 fetchers and client queries in:

- `frontend/src/lib/api/client.ts`
- `frontend/src/components/funds/FundProfileView.tsx`
- `frontend/src/app/funds/[id]/page.tsx`

There is backend catalog cache already:

- `backend/app/core/cache.py`
- `backend/tests/test_catalog_cache.py`

That backend cache is not P6. P6 is specifically the Next frontend layer:

- route handlers under `frontend/src/app/api/funds/...`
- Next cache via `unstable_cache` / `revalidate` / tags
- `Cache-Control` headers
- SSR `QueryClient.prefetchQuery` + `dehydrate` + `HydrationBoundary`

At dispatch creation time, `rg` found no `frontend/src/app/api/funds/**/route.ts`, no `HydrationBoundary`, and no `unstable_cache` in `frontend/src`.

## Preserve Dirty Work

Before editing, run:

```powershell
git status --short --branch
```

At the time this dispatch was written, these unrelated untracked files existed and must not be staged, removed, reformatted, or normalized unless the owner explicitly authorizes it:

- `.idea/AugmentWebviewStateStore.xml`
- `backend/_gate_vs_full_backtest.py`
- `backend/_navdata.csv`
- `backend/_navdata.err`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

## Read First

Read these files before coding:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/dispatch-highcharts-p5-tier-b-dossier.md`
4. `frontend/package.json`
5. `frontend/src/app/funds/[id]/page.tsx`
6. `frontend/src/app/providers.tsx`
7. `frontend/src/components/funds/FundProfileView.tsx`
8. `frontend/src/lib/api/client.ts`
9. `backend/app/core/cache.py`

Use repo truth over this dispatch if the code has moved. Record any drift before changing files.

## Library/API Notes

The current frontend dependencies include:

- `next@15.5.19`
- `@tanstack/react-query@^5.101.0`

For this version, use the App Router-compatible pattern already in the plan:

- `unstable_cache` from `next/cache` with `{ revalidate, tags }`
- `revalidateTag` from `next/cache` only inside a route handler or server action
- route handlers returning `Response` / `NextResponse` with explicit `Cache-Control`
- React Query SSR hydration via a server-side `QueryClient`, `prefetchQuery`, `dehydrate`, and `<HydrationBoundary state={...}>`

Note: current Next docs say `unstable_cache` is superseded by the `use cache` directive in Next 16. Do not migrate to Next 16 APIs in this dispatch unless `frontend/package.json` has actually changed. If it has changed, stop and re-check official docs before implementing.

## Required Opening Verification

Run:

```powershell
rg -n "P6|Caching|unstable_cache|HydrationBoundary|revalidate|Cache-Control|tags" docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md
rg -n "unstable_cache|next/cache|HydrationBoundary|dehydrate|prefetchQuery|Cache-Control|s-maxage|stale-while-revalidate" frontend/src backend/app
rg -n "fetchFund(Profile|Analysis|HoldingsTop|Peers|Factors|StyleDrift|EntityAnalytics|RiskTimeseries|ActiveShare|Timeseries)|queryKey" frontend/src/components/funds/FundProfileView.tsx frontend/src/lib/api/client.ts
```

Expected:

- P4/P5 dossier fetchers exist.
- P5 dossier route renders through `frontend/src/app/funds/[id]/page.tsx`.
- No P6 route handlers/hydration exist yet, unless another session already started them.

## P6 Scope

Implement only P6:

- Next route handlers that proxy cacheable fund dossier GET endpoints.
- A small server-side dossier query layer used by both route handlers and SSR prefetch.
- SSR prefetch for the initial fund dossier page.
- Hydration into the existing client `FundProfileView`.
- Query keys and stale times aligned between SSR and client.
- Cache invalidation route or helper only where it has a concrete event hook.

Do not implement P7, P8, new analytics, backend schema changes, chart redesign, or deploy.

## P6 Non-Scope

- No changes to backend analytics behavior.
- No fake invalidation events.
- No caching for user-specific portfolio routes.
- No caching for authenticated mutations.
- No broad auth rewrite.
- No removal of React Query from client interactions.
- No replacing the backend catalog cache.

## Cacheable Endpoint Set

Start with fund dossier GETs that are public/catalog-like and already consumed by `FundProfileView`:

- `GET /funds/{id}`
- `GET /funds/{id}/timeseries?range=...`
- `GET /funds/{id}/analysis?range=&window=`
- `GET /funds/{id}/holdings/top?limit=`
- `GET /funds/{id}/peers?limit=`
- `GET /funds/scatter?limit=`
- `GET /funds/{id}/factors`
- `GET /funds/{id}/style-drift?quarters=`
- `GET /funds/{id}/risk-timeseries?from=&to=`
- `GET /funds/{id}/entity-analytics?window=&benchmark_id=`
- `GET /funds/{id}/active-share?benchmark_id=`

Do not cache portfolio/user data. If any endpoint requires a user token, do not route it through public P6 caching until the auth/cache boundary is explicitly designed.

## Implementation Tasks

## Execution Progress

- [x] Read dispatch, required docs, current branch/worktree state, and opening verification.
- [x] Implement server-only backend fetch helper, shared dossier cache/query config, and cached route handlers.
- [x] Point fund dossier client queries at the same-origin cache proxy and align stale times.
- [x] Add SSR `QueryClient` prefetch plus `HydrationBoundary` for the first fund dossier paint.
- [x] Add/update unit coverage for query keys, proxy paths/headers/error propagation, and client query wiring.
- [x] Run validation gates and browser evidence pass.

### 1. Create a server-side backend fetch helper

Add a small server-only helper, for example:

- `frontend/src/lib/api/server.ts`

It should:

- run only on the server (`import "server-only"` if available in this stack)
- use the same backend base URL source as the client, but without browser token handling
- fetch JSON from FastAPI
- preserve backend `detail` on errors
- expose typed helpers or a generic `serverRequest<T>(path)`

Do not import `frontend/src/lib/api/client.ts` into Server Components or route handlers if it depends on browser auth token helpers.

### 2. Define dossier query keys in one shared module

Add a query-key module, for example:

- `frontend/src/lib/funds/dossierQueries.ts`

This module should own stable query keys and fetch functions for both SSR and client use.

Required:

- query keys match exactly between server prefetch and client `useQuery`
- params included in keys are normalized (`null` vs `undefined`, default limits, default range)
- no object identity churn in keys

If current `FundProfileView` hardcodes query keys inline, refactor only the fund dossier keys/fetchers needed for P6.

### 3. Add Next route handlers

Create route handlers under `frontend/src/app/api/funds/...`.

Recommended shape:

```text
frontend/src/app/api/funds/[id]/profile/route.ts
frontend/src/app/api/funds/[id]/timeseries/route.ts
frontend/src/app/api/funds/[id]/analysis/route.ts
frontend/src/app/api/funds/[id]/holdings-top/route.ts
frontend/src/app/api/funds/[id]/peers/route.ts
frontend/src/app/api/funds/scatter/route.ts
frontend/src/app/api/funds/[id]/factors/route.ts
frontend/src/app/api/funds/[id]/style-drift/route.ts
frontend/src/app/api/funds/[id]/risk-timeseries/route.ts
frontend/src/app/api/funds/[id]/entity-analytics/route.ts
frontend/src/app/api/funds/[id]/active-share/route.ts
```

Route handler requirements:

- use `unstable_cache` around the FastAPI fetch
- include cache keys with endpoint, fund id, and normalized query params
- include tags:
  - `fund:{id}`
  - `fund:{id}:{subresource}`
  - for scatter, `funds:scatter`
- set `Cache-Control` headers:
  - profile-like endpoints: `s-maxage=300, stale-while-revalidate=900`
  - long historical/analytics endpoints: `s-maxage=3600, stale-while-revalidate=3600`
- propagate non-2xx backend responses with the same status and useful body
- never cache errors intentionally

Prefer a route-handler factory/helper to avoid 11 copy-pasted handlers, but keep it simple enough for App Router conventions.

### 4. Point client-side fetchers at the Next cache proxy where appropriate

Decide one of two patterns and apply consistently:

Preferred:

- keep raw backend fetchers for non-cache use
- add cached/proxy fetchers for fund dossier endpoints
- have `FundProfileView` use cached/proxy fetchers

Alternative:

- update existing fund dossier fetchers in `client.ts` to use same-origin `/api/funds/...`
- keep clearly named raw helpers for direct backend calls if needed elsewhere

Do not route every API call through the proxy. Limit the change to fund dossier GETs.

### 5. Add SSR prefetch + HydrationBoundary

Modify `frontend/src/app/funds/[id]/page.tsx`:

- create a server-side `QueryClient`
- prefetch the first paint's required dossier queries
- use `Promise.all` for independent prefetches
- wrap `<FundProfileView ... />` in `<HydrationBoundary state={dehydrate(queryClient)}>`

Initial prefetch set should include what is visible immediately on first paint:

- profile
- default range timeseries
- analysis for default range/window
- holdings/top
- peers
- factors/style if initially visible or above the fold

Be careful with expensive modal-only data:

- Deep Analysis / entity analytics can remain client-fetched unless the current UI opens it above the fold.
- Risk timeseries can be prefetched only if the Performance tab uses it immediately.
- Active share should not prefetch until benchmark context is known.

### 6. Align stale times

Current provider uses default `staleTime: 30_000`. For hydrated dossier queries:

- set per-query `staleTime` to match the route handler TTL
- avoid immediate client refetch after hydration
- keep `refetchOnWindowFocus: false`

Use the shared query definitions to prevent drift.

### 7. Invalidation

The spec calls for tag invalidation on metric refresh/import events. In this dispatch:

- add the helper or route only if there is a real app event to call it
- otherwise document the missing event hook in code comments or dispatch final report
- do not create an unauthenticated public invalidation endpoint

If an invalidation endpoint is needed:

- require server-side authorization or a secret
- call `revalidateTag("fund:<id>")`
- call subresource tags as needed
- test that it rejects unauthenticated/invalid requests

## Tests

Add or update frontend tests:

- route handler unit tests for:
  - cache headers
  - backend URL/query passthrough
  - non-2xx propagation
  - tag/key normalization where testable
- query key tests for:
  - stable keys
  - normalized default params
- page/hydration tests if existing test setup can render Server Components; otherwise test the query helper layer and route handlers.

Do not require live backend in unit tests.

## Validation Gates

Frontend:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Backend:

P6 is frontend-focused, but run targeted backend cache tests if any backend cache assumptions are touched:

```powershell
cd backend
python -m pytest tests/test_catalog_cache.py -q
```

Browser validation:

- start backend/frontend on free ports
- open a real fund dossier page
- verify first paint does not show the old full-page loading path for prefetched data
- verify network calls go to same-origin `/api/funds/...` for cacheable dossier data
- verify route responses include `Cache-Control`
- reload the page and verify cached route behavior is materially faster or logs show cache hit/reuse
- switch tabs/ranges and verify client React Query still works
- check light/dark if theme controls are available

If precise timing is noisy locally, report concrete evidence from headers/network/request counts instead of claiming performance gains.

## Commit Discipline

Use focused commits. Suggested split:

```powershell
git commit -m "feat(funds): add cached dossier route handlers"
git commit -m "feat(funds): hydrate dossier queries on first paint"
```

Do not stage unrelated untracked files. Before every commit:

```powershell
git status --short
git diff --stat
git diff --cached --name-only
```

## Stop Conditions

Stop and report instead of guessing if:

- `frontend/package.json` has moved to Next 16+ and cache APIs differ from this dispatch.
- the current fund dossier fetchers require browser-only auth state for public GETs.
- route handlers cannot safely reach the backend base URL in the target environment.
- P5 dossier routes are not actually present in the current checkout.
- build/test setup cannot execute route handler tests without large unrelated failures.

## Final Report Shape

Report in Portuguese:

1. Branch and final HEAD SHA(s).
2. Which route handlers/cache tags landed.
3. Which queries are SSR-prefetched and hydrated.
4. Exact gates run and results.
5. Browser evidence: route, headers, first-paint/loading behavior, and same-origin `/api/funds/...` calls.
6. Any skipped gates, missing invalidation event hooks, or unrelated dirty files.

Do not deploy, push, or open PR unless the owner explicitly asks.
