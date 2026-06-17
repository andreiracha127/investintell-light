import { describe, expect, it } from "vitest";
import { authReducer, gateDecision, isPublicPath, type AuthState } from "@/lib/auth/authState";

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
  it("does not redirect authed users", () => {
    expect(gateDecision("authed", "/portfolio")).toBeNull();
  });
});
