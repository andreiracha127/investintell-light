import { describe, expect, it, vi } from "vitest";
import { parseAccessToken, refreshSession } from "@/lib/auth/token";

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
