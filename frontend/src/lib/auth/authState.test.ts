import { describe, expect, it } from "vitest";
import { authReducer, gateDecision, isPublicPath, authGate, safeNextPath, type AuthState } from "@/lib/auth/authState";

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

describe("gateDecision", () => {
  it("never redirects while loading", () => {
    expect(gateDecision("loading", "/portfolio")).toBeNull();
  });
  it("never redirects on /login", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(gateDecision("anon", "/login")).toBeNull();
  });
  it("redirects anon users to /login with next", () => {
    expect(gateDecision("anon", "/portfolio")).toBe("/login?next=%2Fportfolio");
  });
  it("does not redirect anon users away from public funds routes", () => {
    expect(isPublicPath("/funds")).toBe(true);
    expect(isPublicPath("/funds/fund-1")).toBe(true);
    expect(gateDecision("anon", "/funds")).toBeNull();
    expect(gateDecision("anon", "/funds/fund-1")).toBeNull();
  });
  it("does not redirect anon users away from public stock routes", () => {
    expect(isPublicPath("/stocks")).toBe(true);
    expect(isPublicPath("/stocks/AMD")).toBe(true);
    expect(gateDecision("anon", "/stocks")).toBeNull();
    expect(gateDecision("anon", "/stocks/AMD")).toBeNull();
  });
  it("does not redirect authed users", () => {
    expect(gateDecision("authed", "/portfolio")).toBeNull();
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
