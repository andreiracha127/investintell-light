const ACCESS_COOKIE = "insforge_access_token";

/** Pure: extract the access token from a document.cookie-style string. */
export function parseAccessToken(cookieString: string): string | null {
  for (const part of cookieString.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName === ACCESS_COOKIE) {
      return rest.length ? decodeURIComponent(rest.join("=")) : null;
    }
  }
  return null;
}

/** Browser-only: read the current access token from document.cookie. */
export function getAccessToken(): string | null {
  if (typeof document === "undefined") return null;
  return parseAccessToken(document.cookie);
}

export type AuthIdentity = { id: string; email: string };

/** Decode a base64url segment to a UTF-8 string (works in browser and Node). */
function decodeBase64Url(segment: string): string {
  const b64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/**
 * Pure: decode a JWT's payload and extract the user identity. The signature is
 * NOT verified here — the FastAPI backend does that for real on every request;
 * this only reads `sub`/`email` to resolve the client-side auth state from the
 * readable `insforge_access_token` cookie, avoiding a cross-site call to the
 * InsForge auth host (whose refresh always 401s — the refresh token is an
 * httpOnly cookie on this origin and never travels cross-site). Returns null
 * when the token is absent, malformed, missing `sub`, or already expired.
 */
export function identityFromToken(token: string | null): AuthIdentity | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let claims: { sub?: unknown; email?: unknown; exp?: unknown };
  try {
    const parsed: unknown = JSON.parse(decodeBase64Url(parts[1]));
    if (parsed === null || typeof parsed !== "object") return null;
    claims = parsed as typeof claims;
  } catch {
    return null;
  }
  if (typeof claims.sub !== "string" || claims.sub === "") return null;
  if (typeof claims.exp === "number" && claims.exp * 1000 <= Date.now()) return null;
  return { id: claims.sub, email: typeof claims.email === "string" ? claims.email : "" };
}

/** Ask the app refresh route to rotate the access-token cookie. */
export async function refreshSession(fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try {
    const res = await fetchImpl("/api/auth/refresh", { method: "POST", credentials: "include" });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Resolve the client-side identity from the readable access-token cookie, kept
 * fresh by the SSR middleware. If the cookie is missing or expired, try the
 * same-origin refresh route ONCE (server-side it holds the httpOnly refresh
 * token) and re-read the rotated cookie. Stays entirely same-origin — it never
 * calls the cross-site InsForge auth host, which is what produced the 401 loop.
 */
export async function resolveAuthIdentity(
  deps: { readToken?: () => string | null; refresh?: () => Promise<boolean> } = {},
): Promise<AuthIdentity | null> {
  const readToken = deps.readToken ?? getAccessToken;
  const refresh = deps.refresh ?? refreshSession;
  const current = identityFromToken(readToken());
  if (current) return current;
  const refreshed = await refresh();
  return refreshed ? identityFromToken(readToken()) : null;
}
