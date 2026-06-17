import { describe, expect, it, vi } from "vitest";
import {
  identityFromToken,
  parseAccessToken,
  refreshSession,
  resolveAuthIdentity,
} from "@/lib/auth/token";

/** Build a syntactically valid JWT (base64url header.payload.sig) for tests. */
function makeJwt(payload: Record<string, unknown>): string {
  const enc = (obj: unknown) => Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(payload)}.signature`;
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600;
const PAST = Math.floor(Date.now() / 1000) - 3600;

describe("identityFromToken", () => {
  it("extracts id (sub) and email from a valid, unexpired token", () => {
    const token = makeJwt({ sub: "user-123", email: "a@b.c", exp: FUTURE });
    expect(identityFromToken(token)).toEqual({ id: "user-123", email: "a@b.c" });
  });
  it("returns email as empty string when the email claim is absent", () => {
    expect(identityFromToken(makeJwt({ sub: "user-123", exp: FUTURE }))).toEqual({
      id: "user-123",
      email: "",
    });
  });
  it("returns null for an expired token", () => {
    expect(identityFromToken(makeJwt({ sub: "user-123", exp: PAST }))).toBeNull();
  });
  it("returns null when sub is missing", () => {
    expect(identityFromToken(makeJwt({ email: "a@b.c", exp: FUTURE }))).toBeNull();
  });
  it("returns null for a null token", () => {
    expect(identityFromToken(null)).toBeNull();
  });
  it("returns null for malformed tokens", () => {
    expect(identityFromToken("not-a-jwt")).toBeNull();
    expect(identityFromToken("only.two")).toBeNull();
    expect(identityFromToken("a.!!!notbase64!!!.c")).toBeNull();
  });
  it("returns null (never throws) when the payload is not a JSON object", () => {
    const enc = (s: string) => Buffer.from(s).toString("base64url");
    const header = enc(JSON.stringify({ alg: "HS256" }));
    expect(identityFromToken(`${header}.${enc("null")}.sig`)).toBeNull();
    expect(identityFromToken(`${header}.${enc("42")}.sig`)).toBeNull();
    expect(identityFromToken(`${header}.${enc('"a-string"')}.sig`)).toBeNull();
    expect(identityFromToken(`${header}.${enc("[1,2,3]")}.sig`)).toBeNull();
  });
});

describe("parseAccessToken", () => {
  it("extracts insforge_access_token from a cookie string", () => {
    expect(parseAccessToken("a=1; insforge_access_token=abc.def.ghi; b=2")).toBe("abc.def.ghi");
  });
  it("returns null when the cookie is absent", () => {
    expect(parseAccessToken("a=1; b=2")).toBeNull();
  });
  it("returns null for an empty cookie string", () => {
    expect(parseAccessToken("")).toBeNull();
  });
  it("url-decodes the value", () => {
    expect(parseAccessToken("insforge_access_token=ab%2Bcd")).toBe("ab+cd");
  });
});

describe("refreshSession", () => {
  it("POSTs /api/auth/refresh with credentials and resolves true on ok", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true });
    const ok = await refreshSession(fetchImpl as unknown as typeof fetch);
    expect(ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/refresh",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
  it("resolves false on non-ok", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false });
    expect(await refreshSession(fetchImpl as unknown as typeof fetch)).toBe(false);
  });
  it("resolves false when fetch throws", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("network"));
    expect(await refreshSession(fetchImpl as unknown as typeof fetch)).toBe(false);
  });
});

describe("resolveAuthIdentity", () => {
  const valid = makeJwt({ sub: "u1", email: "a@b.c", exp: FUTURE });

  it("returns the identity from the current cookie without refreshing", async () => {
    const refresh = vi.fn();
    const id = await resolveAuthIdentity({ readToken: () => valid, refresh });
    expect(id).toEqual({ id: "u1", email: "a@b.c" });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes once when the cookie is missing, then re-reads the rotated cookie", async () => {
    let token: string | null = null;
    const refresh = vi.fn(async () => {
      token = valid;
      return true;
    });
    const id = await resolveAuthIdentity({ readToken: () => token, refresh });
    expect(id).toEqual({ id: "u1", email: "a@b.c" });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("returns null when refresh fails", async () => {
    expect(
      await resolveAuthIdentity({ readToken: () => null, refresh: async () => false }),
    ).toBeNull();
  });

  it("returns null when refresh succeeds but no valid token appears", async () => {
    expect(
      await resolveAuthIdentity({ readToken: () => null, refresh: async () => true }),
    ).toBeNull();
  });
});
