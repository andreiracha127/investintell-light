import { describe, expect, it } from "vitest";

import {
  buildFundBackendPath,
  buildFundProxyPath,
  buildHoldingReverseLookupBackendPath,
  buildHoldingReverseLookupProxyPath,
  buildFundsScatterProxyPath,
  cacheControlHeader,
  dossierQueryKeys,
  fundResourceCacheKey,
  fundResourceTags,
  holdingReverseLookupCacheKey,
  holdingReverseLookupTags,
  normalizeAnalysisParams,
  normalizeCusip,
  normalizeEntityAnalyticsParams,
  normalizeRiskTimeseriesParams,
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
    expect(dossierQueryKeys.riskTimeseries("fund-1", { benchmark_id: "bench-1" })).toEqual([
      "fund-risk-timeseries",
      "fund-1",
      null,
      null,
      "bench-1",
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
    expect(normalizeRiskTimeseriesParams({ benchmark_id: "  bench-1  " })).toEqual({
      from: null,
      to: null,
      benchmark_id: "bench-1",
    });
  });

  it("builds proxy and backend paths from the same normalized params", () => {
    expect(buildFundProxyPath("holdings-top", "fund/with space", {})).toBe(
      "/api/funds/fund%2Fwith%20space/holdings-top?limit=25",
    );
    expect(buildFundBackendPath("holdings-top", "fund/with space", {})).toBe(
      "/funds/fund%2Fwith%20space/holdings/top?limit=25",
    );
    expect(buildFundProxyPath("risk-timeseries", "fund-1", { benchmark_id: "bench-1" })).toBe(
      "/api/funds/fund-1/risk-timeseries?benchmark_id=bench-1",
    );
    expect(buildFundsScatterProxyPath({})).toBe("/api/funds/scatter?limit=250");
    expect(buildFundProxyPath("institutional-reveal", "fund-1")).toBe(
      "/api/funds/fund-1/institutional-reveal",
    );
    expect(buildHoldingReverseLookupBackendPath("037833-100")).toBe(
      "/holdings/037833100/reverse-lookup",
    );
    expect(buildHoldingReverseLookupProxyPath("037833-100")).toBe(
      "/api/holdings/037833100/reverse-lookup",
    );
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
    expect(fundResourceCacheKey("timeseries", "fund-1", { range: "5Y" })).toEqual([
      "fund-dossier",
      "timeseries",
      "version:daily-cagg-v1",
      "fund-1",
      "range:5Y",
    ]);
    expect(fundResourceCacheKey("analysis", "fund-1", { range: "MAX" })).toEqual([
      "fund-dossier",
      "analysis",
      "fund-1",
      "range:MAX",
      "window:252",
    ]);
    expect(cacheControlHeader("institutional-reveal")).toBe(
      "public, s-maxage=3600, stale-while-revalidate=3600",
    );
    expect(holdingReverseLookupTags("037833-100")).toEqual([
      "holding:037833100:reverse-lookup",
    ]);
    expect(holdingReverseLookupCacheKey("037833-100")).toEqual([
      "fund-dossier",
      "holding-reverse-lookup",
      "037833100",
    ]);
    expect(dossierQueryKeys.holdingReverseLookup("037833-100")).toEqual([
      "holding-reverse-lookup",
      "037833100",
    ]);
    expect(normalizeCusip(" 037833-100 ")).toBe("037833100");
  });
});
