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

const PUBLIC_PATH_PREFIXES = ["/funds", "/login"];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/** Returns the path to redirect to, or null to stay. Never redirects while
 *  loading or already on /login. */
export function gateDecision(status: AuthStatus, pathname: string): string | null {
  if (status === "loading") return null;
  if (pathname === "/login") return null;
  if (isPublicPath(pathname)) return null;
  if (status === "anon") return `/login?next=${encodeURIComponent(pathname)}`;
  return null;
}
