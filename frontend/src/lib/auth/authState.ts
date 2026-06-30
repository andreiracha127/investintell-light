export type AuthUser = { id: string; email: string };
export type AuthStatus = "loading" | "authed" | "anon";
export type AuthState = { status: AuthStatus; user: AuthUser | null };
export type AuthAction =
  | { type: "resolved"; user: AuthUser | null }
  | { type: "signedOut" };

export function authReducer(_state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case "resolved":
      return action.user ? { status: "authed", user: action.user } : { status: "anon", user: null };
    case "signedOut":
      return { status: "anon", user: null };
  }
}

const PUBLIC_PATH_PREFIXES = ["/login"];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

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
