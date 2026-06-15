import { describe, expect, it, vi } from "vitest";
import { createFetchWithAuth } from "@/lib/api/client";

function res(status: number) {
  return { ok: status >= 200 && status < 300, status } as Response;
}

describe("createFetchWithAuth", () => {
  it("injects the Bearer token when a token exists (no cross-origin credentials)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(res(200));
    const f = createFetchWithAuth({ getToken: () => "tok123", refresh: async () => true, onAuthFail: () => {}, fetchImpl });
    await f("http://x/y", {});
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://x/y",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer tok123" }),
      }),
    );
    // The Bearer API must NOT be called with credentials (would force a
    // credentialed-CORS response the backend does not set).
    expect((fetchImpl.mock.calls[0][1] as RequestInit).credentials).toBeUndefined();
  });

  it("omits Authorization when there is no token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(res(200));
    const f = createFetchWithAuth({ getToken: () => null, refresh: async () => false, onAuthFail: () => {}, fetchImpl });
    await f("http://x/y", {});
    const headers = (fetchImpl.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("on 401 refreshes once and retries with the new token", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(res(401)).mockResolvedValueOnce(res(200));
    let token = "old";
    const f = createFetchWithAuth({ getToken: () => token, refresh: async () => { token = "new"; return true; }, onAuthFail: () => {}, fetchImpl });
    const out = await f("http://x/y", {});
    expect(out.status).toBe(200);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect((fetchImpl.mock.calls[1][1] as RequestInit & { headers: Record<string,string> }).headers.Authorization).toBe("Bearer new");
  });

  it("treats 403 the same as 401 (refresh-retry)", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(res(403)).mockResolvedValueOnce(res(200));
    const f = createFetchWithAuth({ getToken: () => "t", refresh: async () => true, onAuthFail: () => {}, fetchImpl });
    expect((await f("http://x/y", {})).status).toBe(200);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("calls onAuthFail and returns the failed response when refresh fails", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(res(401));
    const onAuthFail = vi.fn();
    const f = createFetchWithAuth({ getToken: () => "t", refresh: async () => false, onAuthFail, fetchImpl });
    const out = await f("http://x/y", {});
    expect(out.status).toBe(401);
    expect(onAuthFail).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("does not retry more than once", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(res(401));
    const onAuthFail = vi.fn();
    const f = createFetchWithAuth({ getToken: () => "t", refresh: async () => true, onAuthFail, fetchImpl });
    await f("http://x/y", {});
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(onAuthFail).toHaveBeenCalledTimes(1);
  });
});
