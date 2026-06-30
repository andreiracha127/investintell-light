# Auth Global Gate — All Routes Require Login

**Date:** 2026-06-29
**Status:** Approved design (pending implementation plan)
**Area:** `frontend/` (Next.js App Router + InsForge SSR auth)

## Problem

Authentication is enforced inconsistently. Some routes are treated as public
(accessible without login) and others as user-scoped (login required), so a
logged-out visitor can browse `/stocks` and `/funds`, then gets bounced to
`/login` the moment they click Portfolio/Screener/etc. Worse, a **logged-in**
user on a "public" page is treated as anonymous (the provider forces
`user: null` on public paths), which is jarring and incorrect.

Desired end state: **every page requires login.** `/login` is the only public
route. Once authenticated, global pages (stocks, funds, macro) show global
market data and user-scoped pages (portfolio, screener, builder, statistics)
show the user's own data — exactly as today, but access to *any* page now
uniformly requires a session.

## Current State (as of this spec)

- **`middleware.ts`** — calls InsForge `updateSession` to refresh the session
  cookie for non-public paths. It does **not** redirect. Its `isPublicPath`
  lists `/login` and `/funds`. Matcher: `["/((?!_next/|favicon.ico|api/auth).*)"]`.
- **`src/lib/auth/authState.ts`** — `PUBLIC_PATH_PREFIXES = ["/funds", "/login", "/stocks"]`;
  pure `gateDecision(status, pathname)` returns a `/login?next=…` target for
  anonymous users on non-public paths.
- **`src/components/shell/AppShell.tsx`** — an effect runs `gateDecision` and
  `router.replace`s to login (the actual client-side gate). Renders `/login`
  bare; shows a "Loading…" screen while auth resolves.
- **`src/lib/auth/context.tsx`** (`AuthProvider`) — on a public path it forces
  `dispatch({ resolved, user: null })` **without** resolving identity (source of
  the "logged-in treated as anonymous" bug). On non-public paths it resolves
  identity from the same-origin access-token cookie via `resolveAuthIdentity()`.
- **`src/app/login/page.tsx`** — reads `next`, sanitizes to same-origin relative
  paths, and `router.replace(next)` after sign-in.
- **`src/lib/api/client.ts`** — `fetchWithAuth` attaches the bearer cookie; on
  401/403 it refreshes once and retries; on persistent failure `onAuthFail()`
  **already** redirects to `/login?next=<path+search>`. This covers runtime
  session expiry independent of the page gate.
- **Routes:** `/` redirects to `/stocks`. Pages: `/builder`, `/funds`, `/login`,
  `/macro`, `/portfolio`, `/screener`, `/stocks` (+ `/statistics/*`). The two
  public lists (middleware vs authState) currently disagree.

## Decision

Move the access gate to the **middleware (server-side)**. Chosen over keeping
the client-side gate (which flashes a Loading screen and special-cases public
paths) and over an explicit hybrid: the middleware redirects unauthenticated
users **before** the protected page renders, and runtime expiry is already
handled by `fetchWithAuth.onAuthFail`. `/login` is the only public route.

The gate decision is a **single pure function** consumed by the middleware, so
it is unit-testable without Next.js request plumbing.

## Design

### 1. Pure gate helper — `src/lib/auth/authState.ts`

Replace the React-status-based `gateDecision` with a server-safe pure function:

```
authGate({ pathname, search, authed }): { redirect: string } | null
```

Contract:
- `pathname` starting with `/api/` → return `null` (never redirect API calls;
  the route returns 401 and the client handles it).
- `pathname === "/login"`:
  - `authed` → `{ redirect: <sanitized next from search> or "/" }`.
  - else → `null`.
- any other (page) path:
  - `!authed` → `{ redirect: "/login?next=" + encodeURIComponent(pathname + search) }`.
  - else → `null`.

Open-redirect safety: `next` is honored only when it is a same-origin relative
path (starts with `/`, not `//`); otherwise fall back to `/`. (Mirror the
existing sanitization in `login/page.tsx`.)

Also: `PUBLIC_PATH_PREFIXES → ["/login"]` and keep `isPublicPath` meaning
"is the login route" (used by `AuthProvider`/`AppShell`). Remove the old
`gateDecision`.

### 2. Middleware — `middleware.ts`

- Keep the internal-path short-circuit (`_next/`, `favicon.ico`).
- Call `updateSession(...)` as today and read its `accessToken` from the
  `UpdateSessionResult`. `authed = accessToken != null`.
- Compute `authGate({ pathname, search: nextUrl.search, authed })`.
  - If it returns a redirect → `NextResponse.redirect(new URL(target, request.url))`
    (carry forward the refreshed `Set-Cookie` headers from the session response).
  - Else → return the `updateSession` response (continue).
- Remove the old local `isPublicPath` (the `/funds` exemption is gone; `/login`
  handling lives in `authGate`).
- Matcher unchanged: `["/((?!_next/|favicon.ico|api/auth).*)"]` — `/api/auth/*`
  stays out of the gate so sign-in/refresh/sign-out work; other `/api/*` routes
  are matched (session refreshed) but `authGate` never redirects them.

### 3. `AppShell.tsx`

- Remove the client gate: delete the `gateDecision` + `router.replace` effect
  and the now-unused `useRouter`/`gateDecision` imports.
- Keep: bare render for `/login`, and the "Loading…" screen while identity
  resolves. Simplify the loading guard now that the only public route is
  `/login` (already handled by the bare-render early return).

### 4. `AuthProvider` — `src/lib/auth/context.tsx`

- No logic change beyond the `isPublicPath` semantics flip: with
  `PUBLIC_PATH_PREFIXES = ["/login"]`, identity now resolves on every non-login
  page, fixing the "logged-in user treated as anonymous on stocks/funds" bug.

### 5. Unchanged

- All data fetching: global endpoints stay global, user-scoped stay user-scoped
  via the authenticated cookie. No backend/API changes.
- `login/page.tsx` `next` handling, `/api/auth/*` routes, `fetchWithAuth`
  401→refresh→`onAuthFail` runtime redirect.

## Edge Cases

- **`/` (root):** redirects to `/stocks`. Anonymous hitting `/` → middleware
  redirects to `/login?next=/`; after login, `/` → `/stocks`. Acceptable.
- **Already-authenticated user opens `/login`:** redirected to sanitized `next`
  or `/` (decided: yes, redirect away from login).
- **API calls when unauthenticated:** not redirected by middleware; the route
  returns 401 and `fetchWithAuth.onAuthFail` redirects the SPA to login.
- **Runtime session expiry:** covered by `onAuthFail` (unchanged).
- **Refreshed cookies on redirect:** the redirect response must preserve the
  `Set-Cookie` headers produced by `updateSession`.

## Testing

- `authState.test.ts` — cover `authGate`:
  - anonymous page route → `/login?next=<encoded path+search>`.
  - authenticated `/login` → sanitized `next` or `/`.
  - `/api/...` (auth'd or not) → `null`.
  - open-redirect attempts (`//evil`, `https://evil`) → fall back to `/`.
  - `isPublicPath` true only for `/login`.
- Keep existing `fetchWithAuth` / sign-in route tests green.
- Manual: logged-out → any page redirects to login with correct `next`; after
  login lands on the intended page; navigating stocks→portfolio while logged in
  no longer bounces; `/login` while logged in redirects away.

## Out of Scope

- Sign-up / registration / password-reset flows (no such routes exist today).
- Any change to which data is global vs user-scoped.
- Role/permission tiers beyond authenticated-or-not.

## Success Criteria

- Unauthenticated access to any page except `/login` redirects to
  `/login?next=…` before the page renders (no flash of protected content).
- After login the user lands on the originally-requested page.
- A logged-in user is never treated as anonymous on any page, and navigating
  between global and user-scoped pages never bounces to login.
- `tsc`, `eslint`, and `vitest` all pass.
