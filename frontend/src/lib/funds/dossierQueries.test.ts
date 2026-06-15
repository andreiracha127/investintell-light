import { describe, expect, it } from "vitest";

import {
  buildFundBackendPath,
  buildFundProxyPath,
  buildFundsScatterProxyPath,
  cacheControlHeader,
  dossierQueryKeys,
  fundResourceCacheKey,
  fundResourceTags,
  normalizeAnalysisParams,
  normalizeEntityAnalyticsParams,
} from "@/lib/funds/dossierQueries";

describe("fund dossier query config", () => {
  it("normalizes defaults into stable primitive query keys", () => {
    expect(dossierQueryKeys.analysis("fund-1", {})).toEqual([
      "fund-analysis",
      "fund-1",
      "1Y",
      252,
    ]);
    expect(dossierQueryKeys.entityAnalytics("fund-1", { benchmark_id: "" })).toEqual([
      "fund-entity-analytics",
      "fund-1",
      "1Y",
      null,
    ]);
  });

  it("normalizes query params without object identity churn", () => {
    expect(normalizeAnalysisParams({ range: undefined, window: undefined })).toEqual({
      range: "1Y",
      window: 252,
    });
    expect(normalizeEntityAnalyticsParams({ window: undefined, benchmark_id: "  " })).toEqual({
      window: "1Y",
      benchmark_id: null,
    });
  });

  it("builds proxy and backend paths from the same normalized params", () => {
    expect(buildFundProxyPath("holdings-top", "fund/with space", {})).toBe(
      "/api/funds/fund%2Fwith%20space/holdings-top?limit=25",
    );
    expect(buildFundBackendPath("holdings-top", "fund/with space", {})).toBe(
      "/funds/fund%2Fwith%20space/holdings/top?limit=25",
    );
    expect(buildFundsScatterProxyPath({})).toBe("/api/funds/scatter?limit=250");
  });

  it("keeps cache headers, tags, and key parts granular", () => {
    expect(cacheControlHeader("profile")).toBe(
      "public, s-maxage=300, stale-while-revalidate=900",
    );
    expect(cacheControlHeader("timeseries")).toBe(
      "public, s-maxage=3600, stale-while-revalidate=3600",
    );
    expect(fundResourceTags("timeseries", "fund-1")).toEqual([
      "fund:fund-1",
      "fund:fund-1:timeseries",
    ]);
    expect(fundResourceCacheKey("analysis", "fund-1", { range: "MAX" })).toEqual([
      "fund-dossier",
      "analysis",
      "fund-1",
      "range:MAX",
      "window:252",
    ]);
  });
});
