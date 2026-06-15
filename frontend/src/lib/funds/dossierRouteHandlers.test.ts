import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cacheCalls = vi.hoisted(
  () =>
    [] as {
      keyParts: string[];
      options: { revalidate?: number | false; tags?: string[] };
    }[],
);

vi.mock("next/cache", () => ({
  unstable_cache: (
    fn: () => Promise<unknown>,
    keyParts: string[],
    options: { revalidate?: number | false; tags?: string[] },
  ) => {
    cacheCalls.push({ keyParts, options });
    return fn;
  },
}));

import { GET as fundGet } from "@/app/api/funds/[id]/[sub]/route";
import { GET as holdingReverseGet } from "@/app/api/holdings/[cusip]/reverse-lookup/route";
import { GET as scatterGet } from "@/app/api/funds/scatter/route";

const OLD_API_URL = process.env.NEXT_PUBLIC_API_URL;

beforeEach(() => {
  cacheCalls.length = 0;
  process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
});

afterEach(() => {
  process.env.NEXT_PUBLIC_API_URL = OLD_API_URL;
  vi.unstubAllGlobals();
});

function okFetch(body: unknown) {
  const fetchMock = vi.fn(async (...args: Parameters<typeof fetch>) => {
    void args;
    return Response.json(body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("fund dossier route handlers", () => {
  it("proxies a fund subresource through unstable_cache with long cache headers", async () => {
    const fetchMock = okFetch({ id: "fund-1", series: [] });

    const response = await fundGet(
      new Request("https://app.test/api/funds/fund-1/timeseries"),
      { params: Promise.resolve({ id: "fund-1", sub: "timeseries" }) },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, s-maxage=3600, stale-while-revalidate=3600",
    );
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/funds/fund-1/timeseries?range=1Y",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
    expect(cacheCalls[0]).toMatchObject({
      keyParts: ["fund-dossier", "timeseries", "fund-1", "range:1Y"],
      options: {
        revalidate: 3600,
        tags: ["fund:fund-1", "fund:fund-1:timeseries"],
      },
    });
  });

  it("maps public proxy slugs to backend nested paths and short cache headers", async () => {
    const fetchMock = okFetch({ top_holdings: [] });

    const response = await fundGet(
      new Request("https://app.test/api/funds/fund-1/holdings-top?limit=5"),
      { params: Promise.resolve({ id: "fund-1", sub: "holdings-top" }) },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, s-maxage=300, stale-while-revalidate=900",
    );
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/funds/fund-1/holdings/top?limit=5",
    );
    expect(cacheCalls[0].keyParts).toEqual([
      "fund-dossier",
      "holdings-top",
      "fund-1",
      "limit:5",
    ]);
  });

  it("propagates backend non-2xx bodies without converting them to cache hits", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (...args: Parameters<typeof fetch>) => {
        void args;
        return Response.json(
          { detail: "fund not found" },
          { status: 404, statusText: "Not Found" },
        );
      }),
    );

    const response = await fundGet(
      new Request("https://app.test/api/funds/missing/profile"),
      { params: Promise.resolve({ id: "missing", sub: "profile" }) },
    );

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ detail: "fund not found" });
    expect(cacheCalls[0]).toMatchObject({
      keyParts: ["fund-dossier", "profile", "missing"],
      options: { revalidate: 300, tags: ["fund:missing", "fund:missing:profile"] },
    });
  });

  it("proxies scatter with its own route and tag", async () => {
    const fetchMock = okFetch({ count: 0 });

    const response = await scatterGet(
      new Request("https://app.test/api/funds/scatter"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, s-maxage=300, stale-while-revalidate=900",
    );
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/funds/scatter?limit=250",
    );
    expect(cacheCalls[0]).toMatchObject({
      keyParts: ["fund-dossier", "scatter", "all", "limit:250"],
      options: { revalidate: 300, tags: ["funds:scatter"] },
    });
  });

  it("proxies holding reverse lookup with CUSIP cache tags", async () => {
    const fetchMock = okFetch({ cusip: "037833100", institutions: [] });

    const response = await holdingReverseGet(
      new Request("https://app.test/api/holdings/037833100/reverse-lookup"),
      { params: Promise.resolve({ cusip: "037833100" }) },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, s-maxage=3600, stale-while-revalidate=3600",
    );
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.example.test/holdings/037833100/reverse-lookup",
    );
    expect(cacheCalls[0]).toMatchObject({
      keyParts: ["fund-dossier", "holding-reverse-lookup", "037833100"],
      options: {
        revalidate: 3600,
        tags: ["holding:037833100:reverse-lookup"],
      },
    });
  });
});
