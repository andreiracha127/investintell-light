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

/** Ask the app refresh route to rotate the access-token cookie. */
export async function refreshSession(fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try {
    const res = await fetchImpl("/api/auth/refresh", { method: "POST", credentials: "include" });
    return res.ok;
  } catch {
    return false;
  }
}
