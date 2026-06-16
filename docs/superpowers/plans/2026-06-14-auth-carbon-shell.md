# InsForge Auth + Carbon Shell Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real InsForge-backed authentication (login page, logout, route gating, Bearer token for the FastAPI backend) and refactor the cockpit header's theme/accent controls to official Carbon Design System components.

**Architecture:** Session is handled by `@insforge/sdk/ssr` (session layer only — pages stay client-rendered, FastAPI is not proxied): a Next sign-in route sets a browser-readable `insforge_access_token` cookie + httpOnly `insforge_refresh_token`; `client.ts` reads that cookie for `Authorization: Bearer` and, on 401/403, hits `/api/auth/refresh` once and retries. Carbon is adopted only in the header bar and `/login`; the sidebar, density toggle, and `data-theme/accent/density` localStorage persistence are unchanged. Logic units (cookie parse, refresh, fetch-with-auth, auth reducer, gate decision) are pure/DI so they unit-test in Vitest's node env.

**Tech Stack:** Next 15.5 (App Router) + React 19 + TS 5 + Tailwind v4, `@carbon/react`/`@carbon/styles`/`@carbon/icons-react`, `@insforge/sdk` (+ `/ssr`), TanStack Query v5, Vitest 4.

**Working directory:** `E:/investintell-light/.claude/worktrees/auth-carbon/frontend` (branch `feat/auth-carbon-shell`). Baseline: 73 tests pass; 2 pre-existing screener `.test.tsx` files fail to parse (jsx:preserve) — treat as baseline, do not regress further.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/lib/insforge/browser.ts` | `createBrowserClient()` singleton |
| `src/lib/insforge/server.ts` | `createInsForgeServerClient()` |
| `src/app/api/auth/sign-in/route.ts` | POST: signInWithPassword → setAuthCookies |
| `src/app/api/auth/sign-out/route.ts` | POST: signOut → clear cookies |
| `src/app/api/auth/refresh/route.ts` | POST: `createRefreshAuthRouter()` |
| `middleware.ts` | `updateSession()` |
| `src/lib/auth/token.ts` | `parseAccessToken` (pure) + `getAccessToken` + `refreshSession` |
| `src/lib/auth/authState.ts` | `authReducer` + `gateDecision` (pure) |
| `src/lib/auth/context.tsx` | `AuthProvider` + `useAuth` |
| `src/lib/api/client.ts` | `createFetchWithAuth` + route all fetches through it |
| `src/app/login/page.tsx` | Carbon login form |
| `src/components/shell/AppShell.tsx` | Carbon header + logout + /login bypass + AuthGate + SkipToContent |
| `src/components/shell/CarbonThemeBridge.tsx` | `<Theme>` from data-theme |
| `src/app/layout.tsx` | Carbon CSS + ThemeBridge |
| `src/app/providers.tsx` | wrap in `AuthProvider` |
| `globals.css` | `.ix-carbon-scope` overrides |
| `.env.example` | env docs |

Pure/DI units with tests: `token.ts`, `authState.ts`, `createFetchWithAuth`.

---

## Task 0: Deps, env, Carbon CSS
**Files:** modify `package.json`; create `.env.example`; modify `src/app/layout.tsx`.
- [ ] Step 1: `pnpm add @carbon/react @carbon/styles @carbon/icons-react @insforge/sdk`
- [ ] Step 2: create `.env.example` with `NEXT_PUBLIC_INSFORGE_URL`, `NEXT_PUBLIC_INSFORGE_ANON_KEY`, `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_API_URL`; create `.env.local` with real values (gitignored).
- [ ] Step 3: in `layout.tsx` add `import "@carbon/styles/css/styles.min.css";` after `globals.css`.
- [ ] Step 4: `pnpm build` → resolves Carbon CSS, OK.
- [ ] Step 5: commit `build(auth): add carbon + insforge deps, carbon css, env example`.

## Task 1: InsForge clients
**Files:** create `src/lib/insforge/browser.ts`, `server.ts`.
- [ ] Step 1: `browser.ts` → `"use client"; import { createBrowserClient } from "@insforge/sdk/ssr"; export const insforge = createBrowserClient();`
- [ ] Step 2: `server.ts` → `import { cookies } from "next/headers"; import { createServerClient } from "@insforge/sdk/ssr"; export async function createInsForgeServerClient(){ return createServerClient({ cookies: await cookies() }); }`
- [ ] Step 3: `pnpm typecheck` → 0 errors.
- [ ] Step 4: commit `feat(auth): insforge ssr browser + server clients`.

## Task 2: Auth routes + middleware
**Files:** create `src/app/api/auth/{sign-in,sign-out,refresh}/route.ts`, `middleware.ts`.
- [ ] Step 1: sign-in route — `createServerClient().auth.signInWithPassword(await request.json())`; on `error || !data?.accessToken` return `NextResponse.json({error,message},{status: error?.statusCode ?? 401})`; else `const r=NextResponse.json({user:data.user}); setAuthCookies(r.cookies,{accessToken:data.accessToken, refreshToken:data.refreshToken}); return r;`
- [ ] Step 2: sign-out route — `await createServerClient().auth.signOut(); const r=NextResponse.json({ok:true}); r.cookies.delete("insforge_access_token"); r.cookies.delete("insforge_refresh_token"); return r;`
- [ ] Step 3: refresh route — `export const { POST } = createRefreshAuthRouter();`
- [ ] Step 4: `middleware.ts` — `updateSession({requestCookies:request.cookies, responseCookies:response.cookies})`; `config.matcher = ["/((?!_next/static|_next/image|favicon.ico|api/auth).*)"]`.
- [ ] Step 5: `pnpm typecheck && pnpm build` → OK.
- [ ] Step 6: commit `feat(auth): sign-in/sign-out/refresh routes + session middleware`.

## Task 3: Token bridge (TDD)
**Files:** create `src/lib/auth/token.ts` + `token.test.ts`.
- [ ] Step 1: write failing tests for `parseAccessToken` (extracts `insforge_access_token`, null when absent, null for empty, url-decodes) and `refreshSession(fetchImpl)` (POST `/api/auth/refresh` with `credentials:"include"`, true on ok, false on non-ok, false on throw).
- [ ] Step 2: `npx vitest run src/lib/auth/token.test.ts` → FAIL.
- [ ] Step 3: implement:
```ts
const ACCESS_COOKIE = "insforge_access_token";
export function parseAccessToken(cookieString: string): string | null {
  for (const part of cookieString.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === ACCESS_COOKIE) return rest.length ? decodeURIComponent(rest.join("=")) : null;
  }
  return null;
}
export function getAccessToken(): string | null {
  if (typeof document === "undefined") return null;
  return parseAccessToken(document.cookie);
}
export async function refreshSession(fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try { return (await fetchImpl("/api/auth/refresh", { method: "POST", credentials: "include" })).ok; }
  catch { return false; }
}
```
- [ ] Step 4: `npx vitest run src/lib/auth/token.test.ts` → PASS.
- [ ] Step 5: commit `feat(auth): access-token cookie bridge + refresh helper (TDD)`.

## Task 4: fetchWithAuth (TDD)
**Files:** modify `src/lib/api/client.ts`; create `src/lib/api/fetchWithAuth.test.ts`.
- [ ] Step 1: failing tests for `createFetchWithAuth({getToken,refresh,onAuthFail,fetchImpl})`: injects Bearer+credentials when token; omits Authorization when no token; on 401 refresh once + retry with new token; 403 same as 401; refresh fails → onAuthFail + return failed res, no retry-after; never more than one retry.
- [ ] Step 2: `npx vitest run src/lib/api/fetchWithAuth.test.ts` → FAIL.
- [ ] Step 3: implement `createFetchWithAuth` (DI) — build headers via `Headers(init.headers)`, set `Authorization: Bearer <token>` when present, `credentials:"include"`; first fetch; if 401/403 → `await refresh()`; if refreshed retry once; if still 401/403 → `onAuthFail()`; return res. Add default instance `fetchWithAuth` wired to `getAccessToken`/`refreshSession`/redirect-to-`/login?next=`.
- [ ] Step 4: route the JSON `request<T>` fetch (`:286`) + export builder fetch (`:651`) + funds CSV fetch (`:703`) through `fetchWithAuth` (keep existing init).
- [ ] Step 5: `npx vitest run src/lib/api/fetchWithAuth.test.ts && pnpm typecheck` → PASS, 0 errors.
- [ ] Step 6: commit `feat(auth): Bearer + 401/403 refresh-retry in api client (TDD)`.

## Task 5: Auth state + context (TDD pure parts)
**Files:** create `src/lib/auth/authState.ts` + `authState.test.ts`, `src/lib/auth/context.tsx`.
- [ ] Step 1: failing tests for `authReducer` (resolved→authed/anon; signedOut→anon) and `gateDecision(status,pathname)` (null while loading; null on /login; anon→`/login?next=<enc>`; authed→null).
- [ ] Step 2: `npx vitest run src/lib/auth/authState.test.ts` → FAIL.
- [ ] Step 3: implement `authState.ts` (`AuthUser{id,email}`, `AuthState{status,user}`, `authReducer`, `gateDecision`).
- [ ] Step 4: `npx vitest run src/lib/auth/authState.test.ts` → PASS.
- [ ] Step 5: implement `context.tsx` (`AuthProvider` using `useReducer(authReducer)`, mount `insforge.auth.getCurrentUser()` → dispatch resolved; `signIn` POST `/api/auth/sign-in`; `signOut` POST `/api/auth/sign-out` + `queryClient.clear()` + redirect; `useAuth`).
- [ ] Step 6: `pnpm typecheck`; commit `feat(auth): auth reducer + gate decision (TDD) + AuthProvider`.

## Task 6: Wiring, gating, /login bypass
**Files:** modify `src/app/providers.tsx`, `src/components/shell/AppShell.tsx`.
- [ ] Step 1: in `providers.tsx` wrap children with `<AuthProvider>` inside the QueryClientProvider.
- [ ] Step 2: in `AppShell` top: `const {status}=useAuth(); useEffect(()=>{const t=gateDecision(status,pathname); if(t) router.replace(t);},[status,pathname,router]);` then `if(pathname==="/login") return <>{children}</>;` and `if(status==="loading") return <loading/>;`
- [ ] Step 3: `pnpm typecheck && pnpm build` → OK.
- [ ] Step 4: commit `feat(auth): wrap AuthProvider + route gating + /login bypass`.

## Task 7: Login page (Carbon)
**Files:** create `src/app/login/page.tsx`.
- [ ] Step 1: implement Carbon `Form`+`TextInput`(email)+`PasswordInput`+`Button`+`InlineNotification`; `useAuth().signIn`; redirect to `next` (wrap in `<Suspense>` for `useSearchParams`); root `div` has `ix-carbon-scope`.
- [ ] Step 2: `pnpm typecheck && pnpm build` → `/login` in route list.
- [ ] Step 3: commit `feat(auth): Carbon login page`.

## Task 8: Header refactor (Carbon) + logout
**Files:** modify `src/components/shell/AppShell.tsx`.
- [ ] Step 1: replace `<header>` with Carbon `Header`+`SkipToContent`+`HeaderMenuButton`(nav toggle)+`HeaderName`(brand)+TickerSearch+density(custom)+`HeaderGlobalBar`(theme `HeaderGlobalAction` Light/Asleep; accent `OverflowMenu` oxblood/blue/teal; logout `HeaderGlobalAction` Logout → `useAuth().signOut()`). Keep NAV_ITEMS/sidebar/settings/persistence.
- [ ] Step 2: `id="main-content"` on `<main>`; `const {signOut}=useAuth();`.
- [ ] Step 3: remove old theme `<button>` SVG + `AccentDot` row (+ helper if unused).
- [ ] Step 4: `pnpm typecheck && pnpm lint && pnpm build` → OK.
- [ ] Step 5: commit `feat(shell): Carbon header toggles + logout + SkipToContent`.

## Task 9: Carbon theme + accent bridge
**Files:** create `src/components/shell/CarbonThemeBridge.tsx`; modify `src/app/layout.tsx`, `globals.css`.
- [ ] Step 1: `CarbonThemeBridge` — client component, `<Theme theme>` from `document.documentElement.dataset.theme` (g10/g100) via MutationObserver on `data-theme`. Wrap `<AppShell>` in layout.
- [ ] Step 2: append `.ix-carbon-scope { --cds-interactive/-button-primary(+hover/active)/-link-primary(+hover)/-focus/-border-interactive: var(--color-accent)/var(--ix-accent-hover) }` to `globals.css`.
- [ ] Step 3: `pnpm typecheck && pnpm build` → OK.
- [ ] Step 4: commit `feat(shell): Carbon theme bridge (g10/g100) + scoped accent overrides`.

## Task 10: Full gate + visual verification
- [ ] Step 1: `pnpm typecheck && pnpm lint && pnpm test && pnpm build` → 0 type errors; lint clean; tests pass EXCEPT the 2 pre-existing screener `.test.tsx` baseline failures (no NEW failures); build OK.
- [ ] Step 2: manual/Playwright (needs `.env.local` + test user): logged-out → redirect `/login?next`; sign in → back to next, header logout shows; protected FastAPI calls carry `Authorization: Bearer`; theme/accent toggles update `data-*` + Carbon follows accent; logout clears cookies → `/login`; idle past token TTL → one silent refresh then success.
- [ ] Step 3: final fixup commit if needed.

## Self-review (author)
- Spec coverage: deps/CSS (T0), theme bridge (T9), accent (T9), login (T7), header toggles+logout (T8), a11y (T8), insforge clients (T1), routes+mw (T2), token (T3), fetchWithAuth (T4), context+loading (T5), gating+bypass (T6), tests (T3/4/5), env (T0). All covered.
- Type consistency: `AuthUser{id,email}`, `AuthState{status,user}`, `createFetchWithAuth(deps)`, `gateDecision(status,pathname)`, `parseAccessToken/getAccessToken/refreshSession`, cookie `insforge_access_token` — consistent.
- Deferred: React render tests (jsx:preserve parse bug); OAuth/sign-up/reset; Carbon sidebar/density; IBM Plex.
