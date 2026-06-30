import { describe, expect, it } from "vitest";
import { authReducer, isPublicPath, authGate, safeNextPath, type AuthState } from "@/lib/auth/authState";

const loading: AuthState = { status: "loading", user: null };

describe("authReducer", () => {
  it("resolves to authed with the user", () => {
    const s = authReducer(loading, { type: "resolved", user: { id: "1", email: "a@b.c" } });
    expect(s).toEqual({ status: "authed", user: { id: "1", email: "a@b.c" } });
  });
  it("resolves to anon when user is null", () => {
    expect(authReducer(loading, { type: "resolved", user: null })).toEqual({ status: "anon", user: null });
  });
  it("signed-out goes anon", () => {
    expect(authReducer({ status: "authed", user: { id: "1", email: "a@b.c" } }, { type: "signedOut" }))
      .toEqual({ status: "anon", user: null });
  });
});

describe("isPublicPath", () => {
  it("is true only for the login route", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/stocks")).toBe(false);
    expect(isPublicPath("/stocks/AMD")).toBe(false);
    expect(isPublicPath("/funds")).toBe(false);
    expect(isPublicPath("/portfolio")).toBe(false);
  });
});

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
