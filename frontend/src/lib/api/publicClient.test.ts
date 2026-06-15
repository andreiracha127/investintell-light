import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchFunds,
  fetchFundsCsv,
  fetchFundsScatter,
  fetchMacroRegime,
  fetchMarketOverview,
} from "@/lib/api/client";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("public catalog fetches", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the funds list without Authorization and supports page_size=30", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        page: 1,
        page_size: 30,
        staleness: {
          synced_at: null,
          source_calc_date: null,
          source_nav_max_date: null,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchImpl);

    await fetchFunds({ sort: "aum_usd", dir: "desc", page: 1, page_size: 30 });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/funds?");
    expect(url).toContain("page_size=30");
    expect(init.headers).toBeUndefined();
  });

  it("fetches public catalog endpoints without Authorization", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ gainers: [], losers: [], indices: [], sectors: [] }))
      .mockResolvedValueOnce(jsonResponse({ signals: [], recent_flips: [] }))
      .mockResolvedValueOnce(jsonResponse({ names: [], returns: [], volatilities: [] }))
      .mockResolvedValueOnce(new Response("ticker,name\n", { status: 200 }));
    vi.stubGlobal("fetch", fetchImpl);

    await fetchMarketOverview();
    await fetchMacroRegime();
    await fetchFundsScatter({ limit: 10 });
    await fetchFundsCsv({ sort: "aum_usd" });

    for (const [, init] of fetchImpl.mock.calls as [string, RequestInit][]) {
      expect(init.headers).toBeUndefined();
    }
  });
});
