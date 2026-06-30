# Auth Global Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every page require login, with `/login` the only public route, enforced server-side in the Next.js middleware.

**Architecture:** A single pure `authGate({ pathname, search, authed })` function decides redirects and is unit-tested in isolation. The middleware reads the session via InsForge `updateSession` (its `accessToken` result == authenticated) and delegates to `authGate`, redirecting unauthenticated users to `/login?next=…` before any protected page renders. The redundant client-side gate in `AppShell` is removed; runtime session expiry stays covered by the existing `fetchWithAuth.onAuthFail` redirect.

**Tech Stack:** Next.js App Router (Edge middleware), `@insforge/sdk/ssr`, React, TypeScript, Vitest.

## Global Constraints

- Only `/login` is public; every other page requires authentication.
- `/api/*` is never redirected by the middleware (routes return 401; the client handles it). `/api/auth/*` stays out of the matcher entirely.
- No data-layer changes: global endpoints stay global, user-scoped stay user-scoped via the authenticated cookie.
- Open-redirect guard: a `next` value is honored only when it is a same-origin relative path (starts with `/`, not `//`); otherwise fall back to `/`.
- `authState.ts` must stay free of browser/Node-only APIs (it is imported by Edge middleware).
- Path alias `@/*` → `frontend/src/*` (works in `frontend/middleware.ts`).
- Gates run from `frontend/`: `pnpm exec vitest run <file>`, `pnpm exec tsc --noEmit`, `pnpm exec eslint <files>`.
- End every commit message with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `frontend/src/lib/auth/authState.ts` — add pure `authGate` + `safeNextPath`; later flip `PUBLIC_PATH_PREFIXES` to `["/login"]` and delete `gateDecision`.
- `frontend/src/lib/auth/authState.test.ts` — add `authGate` tests; later swap `gateDecision` tests for an `isPublicPath` block.
- `frontend/middleware.ts` — delegate the access decision to `authGate`, redirect server-side.
- `frontend/src/components/shell/AppShell.tsx` — remove the client-side gate effect and now-unused imports.
- `frontend/src/lib/auth/context.tsx` — unchanged (behavior corrected via the `PUBLIC_PATH_PREFIXES` flip).

---

## Task 1: Pure `authGate` helper

Add the gate decision as a self-contained, tested pure function. Nothing consumes it yet, so the build and all existing tests stay green.

**Files:**
- Modify: `frontend/src/lib/auth/authState.ts`
- Test: `frontend/src/lib/auth/authState.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `safeNextPath(raw: string | null): string`
  - `authGate(input: { pathname: string; search: string; authed: boolean }): { redirect: string } | null`

- [ ] **Step 1: Write the failing tests**

Add this block to `frontend/src/lib/auth/authState.test.ts` (after the `authReducer` describe). Also add `authGate, safeNextPath` to the existing import from `@/lib/auth/authState`:

```ts
describe("authGate", () => {
  it("redirects an anonymous user on a page route to /login with next", () => {
    expect(authGate({ pathname: "/portfolio", search: "", authed: false }))
      .toEqual({ redirect: "/login?next=%2Fportfolio" });
  });
  it("preserves the query string in next", () => {
    expect(authGate({ pathname: "/stocks/AAPL", search: "?range=1Y", authed: false }))
      .toEqual({ redirect: "/login?next=%2Fstocks%2FAAPL%3Frange%3D1Y" });
  });
  it("lets an authenticated user through a page route", () => {
    expect(authGate({ pathname: "/portfolio", search: "", authed: true })).toBeNull();
  });
  it("never redirects /api/* routes", () => {
    expect(authGate({ pathname: "/api/backend/x", search: "", authed: false })).toBeNull();
    expect(authGate({ pathname: "/api/backend/x", search: "", authed: true })).toBeNull();
  });
  it("sends an authenticated user away from /login to a safe next", () => {
    expect(authGate({ pathname: "/login", search: "?next=%2Fscreener", authed: true }))
      .toEqual({ redirect: "/screener" });
  });
  it("falls back to / when /login has no next", () => {
    expect(authGate({ pathname: "/login", search: "", authed: true })).toEqual({ redirect: "/" });
  });
  it("blocks open-redirect next values", () => {
    expect(authGate({ pathname: "/login", search: "?next=https://evil.com", authed: true }))
      .toEqual({ redirect: "/" });
    expect(authGate({ pathname: "/login", search: "?next=//evil.com", authed: true }))
      .toEqual({ redirect: "/" });
  });
  it("leaves an anonymous user on /login", () => {
    expect(authGate({ pathname: "/login", search: "", authed: false })).toBeNull();
  });
});

describe("safeNextPath", () => {
  it("keeps same-origin relative paths", () => {
    expect(safeNextPath("/screener")).toBe("/screener");
  });
  it("rejects absolute and protocol-relative urls", () => {
    expect(safeNextPath("https://evil.com")).toBe("/");
    expect(safeNextPath("//evil.com")).toBe("/");
    expect(safeNextPath(null)).toBe("/");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/lib/auth/authState.test.ts`
Expected: FAIL — `authGate`/`safeNextPath` are not exported.

- [ ] **Step 3: Implement `authGate` + `safeNextPath`**

Append to `frontend/src/lib/auth/authState.ts` (after the existing `gateDecision` function — do NOT remove `gateDecision` yet; `AppShell` still imports it):

```ts
/** Same-origin relative path, or "/" for anything else (open-redirect guard). */
export function safeNextPath(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

/**
 * Server-side access gate. Pure so the middleware can delegate the whole
 * decision here and keep it unit-testable. `search` is the raw query string,
 * with or without a leading "?". Returns the path to redirect to, or null to
 * let the request through.
 *  - /api/* is never redirected (the route returns 401; the client handles it).
 *  - /login: an authed user is sent to their sanitized `next` (or "/"); an
 *    anonymous user stays.
 *  - any other page: an anonymous user is sent to /login?next=<path+search>.
 */
export function authGate(input: {
  pathname: string;
  search: string;
  authed: boolean;
}): { redirect: string } | null {
  const { pathname, search, authed } = input;
  if (pathname.startsWith("/api/")) return null;
  if (pathname === "/login") {
    if (!authed) return null;
    const next = new URLSearchParams(search.replace(/^\?/, "")).get("next");
    return { redirect: safeNextPath(next) };
  }
  if (!authed) {
    return { redirect: `/login?next=${encodeURIComponent(pathname + search)}` };
  }
  return null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/lib/auth/authState.test.ts`
Expected: PASS (all `authGate`, `safeNextPath`, existing `authReducer` and `gateDecision` tests green).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/auth/authState.ts frontend/src/lib/auth/authState.test.ts
git commit -m "feat(auth): pure authGate helper for server-side route gating

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Enforce the gate in the middleware

Wire the middleware to `updateSession` + `authGate` so unauthenticated users are redirected server-side before a protected page renders.

**Files:**
- Modify (full rewrite): `frontend/middleware.ts`

**Interfaces:**
- Consumes: `authGate` from `@/lib/auth/authState` (Task 1).
- Produces: server-side redirects; no new exported symbols.

- [ ] **Step 1: Rewrite the middleware**

Replace the entire contents of `frontend/middleware.ts` with:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@insforge/sdk/ssr";
import { authGate } from "@/lib/auth/authState";

// Next 15's RequestCookies/ResponseCookies do not structurally match the SDK's
// CookieStore type (the `.set` overloads differ), though they are
// runtime-compatible. Cast to the helper's own parameter types.
type UpdateSessionArg = Parameters<typeof updateSession>[0];

function isInternalPath(pathname: string): boolean {
  return pathname.startsWith("/_next/") || pathname === "/favicon.ico";
}

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });
  const { pathname, search } = request.nextUrl;
  if (isInternalPath(pathname)) return response;

  // Refresh the session cookie. `accessToken` is non-null when the user has a
  // valid (or just-refreshed) session.
  const { accessToken } = await updateSession({
    requestCookies: request.cookies as unknown as UpdateSessionArg["requestCookies"],
    responseCookies: response.cookies as unknown as UpdateSessionArg["responseCookies"],
  });

  const gate = authGate({ pathname, search, authed: accessToken != null });
  if (gate) {
    const redirect = NextResponse.redirect(new URL(gate.redirect, request.url));
    // Preserve the refreshed Set-Cookie headers on the redirect response.
    for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie);
    return redirect;
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/|favicon.ico|api/auth).*)"],
};
```

(The decision logic is fully covered by the Task 1 `authGate` unit tests; the middleware itself is verified by the server-observable redirects below — mocking `updateSession` + `NextRequest`/`NextResponse` adds fragile plumbing for no extra coverage.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`
Expected: exit 0 (no errors; confirms the `@/lib/auth/authState` import and `UpdateSessionResult.accessToken` usage resolve).

- [ ] **Step 3: Verify the redirect with the dev server (anonymous)**

Start the dev server if not running: `cd frontend && pnpm dev` (note the port, e.g. 3001).
With NO auth cookie, run:

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:3001/portfolio
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:3001/stocks
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3001/login
```

Expected:
- `/portfolio` → `307 http://localhost:3001/login?next=%2Fportfolio`
- `/stocks` → `307 http://localhost:3001/login?next=%2Fstocks`
- `/login` → `200`

- [ ] **Step 4: Commit**

```bash
git add frontend/middleware.ts
git commit -m "feat(auth): gate all routes server-side in middleware via authGate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Single public route + remove the client-side gate

Flip `/login` to the only public path (fixes the AuthProvider treating logged-in users as anonymous on stocks/funds) and delete the now-redundant client gate.

**Files:**
- Modify: `frontend/src/lib/auth/authState.ts`
- Modify: `frontend/src/lib/auth/authState.test.ts`
- Modify: `frontend/src/components/shell/AppShell.tsx`

**Interfaces:**
- Consumes: `authGate` (Task 1, now the only gate), `isPublicPath` (still used by `AuthProvider`).
- Produces: removes `gateDecision` from `authState.ts`.

- [ ] **Step 1: Update the tests first (swap gateDecision tests for isPublicPath)**

In `frontend/src/lib/auth/authState.test.ts`:
1. Remove `gateDecision` from the import line, leaving `import { authReducer, authGate, isPublicPath, safeNextPath, type AuthState } from "@/lib/auth/authState";`.
2. Delete the entire `describe("gateDecision", ...)` block.
3. Add this block:

```ts
describe("isPublicPath", () => {
  it("is true only for the login route", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/stocks")).toBe(false);
    expect(isPublicPath("/stocks/AMD")).toBe(false);
    expect(isPublicPath("/funds")).toBe(false);
    expect(isPublicPath("/portfolio")).toBe(false);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/lib/auth/authState.test.ts`
Expected: FAIL — `isPublicPath("/stocks")` is still `true` (PUBLIC_PATH_PREFIXES not yet changed).

- [ ] **Step 3: Flip the public prefixes and delete `gateDecision`**

In `frontend/src/lib/auth/authState.ts`:
1. Change the prefixes constant to exactly:

```ts
const PUBLIC_PATH_PREFIXES = ["/login"];
```

2. Delete the entire `gateDecision` function (the block starting with its `/** Returns the path to redirect to … */` doc comment through its closing brace). Keep `isPublicPath`, `authGate`, `safeNextPath`, `authReducer`, and the type exports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/lib/auth/authState.test.ts`
Expected: PASS.

- [ ] **Step 5: Remove the client-side gate from `AppShell`**

In `frontend/src/components/shell/AppShell.tsx`, make exactly these edits:

1. Line 13 — drop `useRouter`:

```ts
import { usePathname } from "next/navigation";
```

2. Line 32 — delete the import entirely (neither symbol is used after this task):

```ts
// (removed) import { gateDecision, isPublicPath } from "@/lib/auth/authState";
```

3. In the component body, delete `const router = useRouter();` and `const isPublicRoute = isPublicPath(pathname);`.

4. Delete the gate effect:

```ts
// (removed)
// useEffect(() => {
//   const target = gateDecision(status, pathname);
//   if (target) router.replace(target);
// }, [status, pathname, router]);
```

5. Simplify the loading guard to drop `isPublicRoute`:

```ts
  // Don't flash the app while the session resolves (the /login route already
  // returned bare above).
  if (status === "loading") {
    return <div className="flex h-screen items-center justify-center text-text-muted">Loading…</div>;
  }
```

- [ ] **Step 6: Typecheck, lint, and test the touched files**

Run:
```bash
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint src/components/shell/AppShell.tsx src/lib/auth/authState.ts src/lib/auth/authState.test.ts middleware.ts
pnpm exec vitest run src/lib/auth/authState.test.ts
```
Expected: `tsc` exit 0 (no unused `useRouter`/`gateDecision`/`isPublicPath`), `eslint` exit 0, vitest PASS.

- [ ] **Step 7: Manual end-to-end check**

With the dev server running and a logged-in session:
- Navigate Stocks → Portfolio → Funds: no bounce to `/login`; the account menu shows the real user on every page.
- Visit `/login` while logged in → redirected to `/` (then `/stocks`).
- Sign out, then open `/screener` → redirected to `/login?next=%2Fscreener`; after signing in you land on `/screener`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/auth/authState.ts frontend/src/lib/auth/authState.test.ts frontend/src/components/shell/AppShell.tsx
git commit -m "feat(auth): single public route (/login); drop redundant client gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Server-side middleware gate → Task 2. ✔
- `/login` only public route → Task 3 (`PUBLIC_PATH_PREFIXES = ["/login"]`). ✔
- Pure testable `authGate` → Task 1. ✔
- `/api/*` never redirected → Task 1 `authGate` + tests. ✔
- Authed user redirected away from `/login` → Task 1 + manual check (Task 3 Step 7). ✔
- Open-redirect guard → Task 1 `safeNextPath` + tests. ✔
- Remove client `gateDecision`; keep `onAuthFail` runtime redirect → Task 3 (AppShell) ; `client.ts` untouched. ✔
- AuthProvider bug fix (resolve identity on all non-login pages) → Task 3 prefixes flip; `context.tsx` unchanged. ✔
- No data-layer changes → no API/backend files touched. ✔
- Preserve refreshed cookies on redirect → Task 2 cookie copy loop. ✔

**Placeholder scan:** none — every code/edit step shows full content and exact commands.

**Type consistency:** `authGate({ pathname, search, authed })` and its `{ redirect: string } | null` return are used identically in Task 1 (definition/tests) and Task 2 (middleware). `safeNextPath(string | null): string` consistent across definition and tests. `isPublicPath` signature unchanged.
