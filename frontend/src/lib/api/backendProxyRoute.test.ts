import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  GET,
  POST,
} from "@/app/api/backend/[...path]/route";

const OLD_API_URL = process.env.NEXT_PUBLIC_API_URL;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
});

afterEach(() => {
  process.env.NEXT_PUBLIC_API_URL = OLD_API_URL;
  vi.unstubAllGlobals();
});

function routeParams(path: string[]) {
  return { params: Promise.resolve({ path }) };
}

describe("backend proxy route", () => {
  it("forwards GET paths, query strings, and selected headers to the backend", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({ state: "risk_on" }, { headers: { "Cache-Control": "no-store" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request("https://app.test/api/backend/macro/regime?window=1Y", {
        headers: { Accept: "application/json", Authorization: "Bearer token" },
      }),
      routeParams(["macro", "regime"]),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ state: "risk_on" });
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/macro/regime?window=1Y",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "GET",
      cache: "no-store",
    });
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("authorization")).toBe("Bearer token");
  });

  it("forwards POST JSON bodies through the proxy", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("https://app.test/api/backend/portfolio/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "weights" }),
      }),
      routeParams(["portfolio", "analysis"]),
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/portfolio/analysis",
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect(Buffer.from(init.body as ArrayBuffer).toString("utf8")).toBe(
      JSON.stringify({ mode: "weights" }),
    );
  });
});
