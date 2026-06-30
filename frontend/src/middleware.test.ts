import { beforeEach, describe, expect, it, vi } from "vitest";

// The middleware reads auth state purely from `updateSession`'s result, so we
// mock it to drive `accessToken` (the authed signal) and to optionally write a
// refreshed cookie onto the response — exercising the cookie-copy-onto-redirect
// path that only runs at the server edge (untested by the pure authGate unit).
const updateSession = vi.hoisted(() => vi.fn());

vi.mock("@insforge/sdk/ssr", () => ({ updateSession }));

import { NextRequest } from "next/server";
import { middleware } from "./middleware";

function req(path: string): NextRequest {
  return new NextRequest(new URL(path, "https://app.test"));
}

/** Make `updateSession` resolve with the given access token; optionally have it
 *  set a cookie on the response cookies (as a real refresh/clear would). */
function mockSession(
  accessToken: string | null,
  setCookie?: { name: string; value: string },
): void {
  updateSession.mockImplementation(
    async (args: { responseCookies: { set: (n: string, v: string) => void } }) => {
      if (setCookie) args.responseCookies.set(setCookie.name, setCookie.value);
      return { refreshed: false, accessToken, error: null };
    },
  );
}

describe("middleware (server-side auth gate)", () => {
  beforeEach(() => {
    updateSession.mockReset();
  });

  it("redirects an anonymous page request to /login with an encoded next", async () => {
    mockSession(null);
    const res = await middleware(req("/portfolio"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://app.test/login?next=%2Fportfolio");
  });

  it("preserves the query string in the next param", async () => {
    mockSession(null);
    const res = await middleware(req("/stocks/AAPL?range=1Y"));
    expect(res.headers.get("location")).toBe(
      "https://app.test/login?next=%2Fstocks%2FAAPL%3Frange%3D1Y",
    );
  });

  it("lets an authenticated user through a page route without redirecting", async () => {
    mockSession("valid.jwt.token");
    const res = await middleware(req("/portfolio"));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("never redirects /api/* routes (anonymous)", async () => {
    mockSession(null);
    const res = await middleware(req("/api/backend/stocks/overview"));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("redirects an authenticated user away from /login to a safe next", async () => {
    mockSession("valid.jwt.token");
    const res = await middleware(req("/login?next=%2Fscreener"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://app.test/screener");
  });

  it("skips internal paths without touching the session", async () => {
    const res = await middleware(req("/_next/static/chunk.js"));
    expect(res.status).toBe(200);
    expect(updateSession).not.toHaveBeenCalled();
  });

  it("carries refreshed session cookies onto the redirect response", async () => {
    mockSession(null, { name: "insforge_access_token", value: "fresh" });
    const res = await middleware(req("/portfolio"));
    expect(res.status).toBe(307);
    expect(res.cookies.get("insforge_access_token")?.value).toBe("fresh");
  });
});
