# InsForge Auth + Carbon Shell Refactor — Design Spec

**Date:** 2026-06-14
**Branch:** `feat/auth-carbon-shell` (worktree off `main`)
**Status:** Design — approved (auth token-flow = `@insforge/sdk/ssr`).

## Goal

Add a real authentication system (login, logout, route protection) backed by InsForge, and refactor the cockpit shell's settings controls (theme + accent toggles) to use official Carbon Design System components — **Option 1 (low risk)**: Carbon real only in the **header bar** and the **/login page**; the sidebar/nav and the density toggle stay on the current Tailwind/Graphite implementation for now.

## Resolved decisions

- **Carbon adoption:** full `@carbon/react` for the login page + header controls (header bar only).
- **Auth backend:** real auth against **InsForge** (issuer of the HS256 JWT; the FastAPI backend only *verifies*).
- **Token flow:** **`@insforge/sdk/ssr`** session layer. `getCurrentUser()` does not return the rotated access token, so a separate-backend Bearer needs the SSR helpers' browser-readable `insforge_access_token` cookie + refresh route. Session layer only — pages are NOT migrated to SSR rendering and FastAPI is NOT proxied.
- **Route protection:** gate unauthenticated users to `/login`; handle 401/403 globally with one refresh-retry.

## Research findings baked in

- `signInWithPassword()` → `{ data: { user, accessToken, refreshToken?, csrfToken }, error }` (token only at sign-in).
- `getCurrentUser()` → `{ data: { user }, error }` (no token).
- `@insforge/sdk/ssr` cookies: `insforge_access_token` (readable Bearer) + `insforge_refresh_token` (httpOnly), both expiring at JWT `exp`; refresh via `/api/auth/refresh`.
- Helpers: `createBrowserClient()`, `createServerClient({cookies})`, `setAuthCookies(response.cookies, {accessToken, refreshToken})`, `createRefreshAuthRouter()`, `updateSession({requestCookies, responseCookies})`.

## Corrections folded in (from review)

1. `@carbon/styles` as an explicit dependency (pnpm) for `@carbon/styles/css/styles.min.css`.
2. `PasswordInput` from `@carbon/react` (not `TextInput.PasswordInput`).
3. Carbon theme map: `light → "g10"`, `dark → "g100"`.
4. Keep the current font (`var(--font-sans)`, `globals.css:164`); no IBM Plex global swap.
5. Env: `NEXT_PUBLIC_INSFORGE_URL` + `NEXT_PUBLIC_INSFORGE_ANON_KEY` (+ optional `NEXT_PUBLIC_APP_URL`).
6. Auth loading state: never redirect while `getCurrentUser()` is pending (cold load).
7. 401/403 centralized in `fetchWithAuth` over the JSON `request<T>` (`client.ts:274`) + the two CSV fetches (`:651`, `:703`); treat both 401 and 403.
8. Tests: pure node `.test.ts` units this PR. NOTE: on `main` `vitest.config.ts` supports `.test.tsx` via `@vitejs/plugin-react`, BUT existing `.test.tsx` files fail to parse (tsconfig `jsx: preserve` vs vite-react) — so React render tests stay deferred (same outcome, different reason). Baseline already has 2 failing screener `.test.tsx` files (pre-existing, out of scope).

## Architecture

### 1. Carbon (header + login only)
- Deps: `@carbon/react`, `@carbon/styles`, `@carbon/icons-react`. CSS: `@carbon/styles/css/styles.min.css`.
- Theme bridge: Carbon `<Theme theme>` from `data-theme` (`light→g10`, `dark→g100`). `data-*` stays source of truth.
- Accent bridge: scoped `.ix-carbon-scope` overrides `--cds-button-primary`(+hover/active), `--cds-interactive`, `--cds-focus`, `--cds-border-interactive`, `--cds-link-primary` → `var(--color-accent)`.

### 2. InsForge session layer (`@insforge/sdk/ssr`)
- `src/lib/insforge/browser.ts` (`createBrowserClient()`), `src/lib/insforge/server.ts` (`createServerClient`).
- Routes: `api/auth/sign-in` (signInWithPassword → setAuthCookies), `api/auth/sign-out` (signOut + clear cookies), `api/auth/refresh` (`createRefreshAuthRouter()`).
- `middleware.ts` `updateSession`.

### 3. Auth context + token bridge
- `src/lib/auth/context.tsx` — `AuthProvider`/`useAuth` (getCurrentUser → {user, status loading/authed/anon}; signIn via route; signOut via route + clear RQ cache).
- `src/lib/auth/token.ts` — `parseAccessToken(cookieStr)` (pure) + `getAccessToken()` + `refreshSession()`.
- `src/lib/auth/authState.ts` — `authReducer` + `gateDecision(status, pathname)` (pure).

### 4. API client — `client.ts`
- `createFetchWithAuth(deps)` (DI, testable) → attaches Bearer + `credentials:"include"`; 401/403 → refresh once → retry → else onAuthFail (redirect `/login?next=`). Route all three fetches through it.

### 5. Route gating
- `AuthGate` in `AppShell`: loading → render loading (no redirect); anon & ≠/login → `/login?next=`. `/login` bypasses the shell.

### 6. Login page — `src/app/login/page.tsx`
- Carbon `Form` + `TextInput` + `PasswordInput` + `Button` + `InlineNotification`. Centered.

### 7. Header — `AppShell.tsx`
- Carbon `Header` + `HeaderName` + `HeaderGlobalBar`: theme `HeaderGlobalAction` (Light/Asleep), accent `OverflowMenu`, logout `HeaderGlobalAction` (Logout). `SkipToContent` + `id="main-content"`. Sidebar/density/TickerSearch unchanged. Persistence (`ix-cockpit-settings` + `SETTINGS_SCRIPT` + `data-*`) unchanged.

## Testing
- Pure node `.test.ts`: `token.ts`, `authState.ts`, `createFetchWithAuth`.
- Gate: typecheck + lint + test (allow the 2 pre-existing screener `.test.tsx` baseline failures) + build.

## Prerequisites
1. `.env.local`: `NEXT_PUBLIC_INSFORGE_URL`, `NEXT_PUBLIC_INSFORGE_ANON_KEY` (+ `NEXT_PUBLIC_APP_URL`) + an email/password user — needed only for the T10 live verification.

## Out of scope
- SSR page rendering / FastAPI proxy; Carbon sidebar/density; IBM Plex font; OAuth/sign-up/password-reset.
