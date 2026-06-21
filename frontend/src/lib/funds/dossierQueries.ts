import type {
  FundActiveShareQuery,
  FundAnalysisQuery,
  FundEntityAnalyticsQuery,
  FundHoldingsTopQuery,
  FundPeersQuery,
  FundRiskTimeseriesQuery,
  FundStyleDriftQuery,
  FundsScatterQuery,
  RangePreset,
} from "@/lib/api/client";

type QueryValue = string | number | null | undefined;

export const FUND_DOSSIER_DEFAULTS = {
  range: "1Y" as RangePreset,
  analysisWindow: 252,
  holdingsTopLimit: 25,
  peersLimit: 10,
  scatterLimit: 250,
  styleDriftQuarters: 40,
  entityWindow: "1Y",
  historyBars: 2520,
} as const;

export type FundDossierSubresource =
  | "profile"
  | "timeseries"
  | "history"
  | "analysis"
  | "holdings-top"
  | "peers"
  | "factors"
  | "style-drift"
  | "risk-timeseries"
  | "entity-analytics"
  | "active-share"
  | "institutional-reveal";

export type FundsDossierResource =
  | FundDossierSubresource
  | "scatter"
  | "holding-reverse-lookup";

const FUND_TIMESERIES_CACHE_VERSION = "daily-cagg-v1";

type CacheTier = "short" | "long";

const CACHE_SECONDS_BY_TIER = {
  short: 300,
  long: 3600,
} as const satisfies Record<CacheTier, number>;

const SWR_SECONDS_BY_TIER = {
  short: 900,
  long: 3600,
} as const satisfies Record<CacheTier, number>;

const CACHE_TIER_BY_RESOURCE = {
  profile: "short",
  timeseries: "long",
  history: "long",
  analysis: "long",
  "holdings-top": "short",
  peers: "short",
  factors: "long",
  "style-drift": "long",
  "risk-timeseries": "long",
  "entity-analytics": "long",
  "active-share": "short",
  "institutional-reveal": "long",
  scatter: "short",
  "holding-reverse-lookup": "long",
} as const satisfies Record<FundsDossierResource, CacheTier>;

export const FUND_DOSSIER_REVALIDATE_SECONDS = Object.fromEntries(
  Object.entries(CACHE_TIER_BY_RESOURCE).map(([resource, tier]) => [
    resource,
    CACHE_SECONDS_BY_TIER[tier],
  ]),
) as Record<FundsDossierResource, number>;

export const FUND_DOSSIER_STALE_TIME_MS = Object.fromEntries(
  Object.entries(FUND_DOSSIER_REVALIDATE_SECONDS).map(([resource, seconds]) => [
    resource,
    seconds * 1000,
  ]),
) as Record<FundsDossierResource, number>;

function cleanString(value: QueryValue): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text === "" ? null : text;
}

function stringParam(value: QueryValue, fallback: string): string {
  return cleanString(value) ?? fallback;
}

function integerParam(value: QueryValue, fallback: number): number | string {
  const text = cleanString(value);
  if (text === null) return fallback;
  const parsed = Number(text);
  return Number.isInteger(parsed) ? parsed : text;
}

function searchParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.has(key) ? searchParams.get(key) : null;
}

export function normalizeTimeseriesParams(query: { range?: QueryValue } = {}) {
  return { range: stringParam(query.range, FUND_DOSSIER_DEFAULTS.range) };
}

export function normalizeHistoryParams(query: { bars?: QueryValue } = {}) {
  return { bars: integerParam(query.bars, FUND_DOSSIER_DEFAULTS.historyBars) };
}

export function normalizeAnalysisParams(query: FundAnalysisQuery | { range?: QueryValue; window?: QueryValue } = {}) {
  return {
    range: stringParam(query.range, FUND_DOSSIER_DEFAULTS.range),
    window: integerParam(query.window, FUND_DOSSIER_DEFAULTS.analysisWindow),
  };
}

export function normalizeHoldingsTopParams(query: FundHoldingsTopQuery | { limit?: QueryValue } = {}) {
  return { limit: integerParam(query.limit, FUND_DOSSIER_DEFAULTS.holdingsTopLimit) };
}

export function normalizePeersParams(query: FundPeersQuery | { limit?: QueryValue } = {}) {
  return { limit: integerParam(query.limit, FUND_DOSSIER_DEFAULTS.peersLimit) };
}

export function normalizeScatterParams(query: FundsScatterQuery | { limit?: QueryValue } = {}) {
  return { limit: integerParam(query.limit, FUND_DOSSIER_DEFAULTS.scatterLimit) };
}

export function normalizeStyleDriftParams(query: FundStyleDriftQuery | { quarters?: QueryValue } = {}) {
  return { quarters: integerParam(query.quarters, FUND_DOSSIER_DEFAULTS.styleDriftQuarters) };
}

export function normalizeRiskTimeseriesParams(query: FundRiskTimeseriesQuery | { from?: QueryValue; to?: QueryValue } = {}) {
  return {
    from: cleanString(query.from),
    to: cleanString(query.to),
  };
}

export function normalizeEntityAnalyticsParams(
  query: FundEntityAnalyticsQuery | { window?: QueryValue; benchmark_id?: QueryValue } = {},
) {
  return {
    window: stringParam(query.window, FUND_DOSSIER_DEFAULTS.entityWindow),
    benchmark_id: cleanString(query.benchmark_id),
  };
}

export function normalizeActiveShareParams(query: FundActiveShareQuery | { benchmark_id?: QueryValue } = {}) {
  return { benchmark_id: cleanString(query.benchmark_id) };
}

export function normalizeFundResourceParams(
  resource: FundDossierSubresource,
  query: Record<string, QueryValue> = {},
) {
  switch (resource) {
    case "profile":
    case "factors":
    case "institutional-reveal":
      return {};
    case "timeseries":
      return normalizeTimeseriesParams(query);
    case "history":
      return normalizeHistoryParams(query);
    case "analysis":
      return normalizeAnalysisParams(query);
    case "holdings-top":
      return normalizeHoldingsTopParams(query);
    case "peers":
      return normalizePeersParams(query);
    case "style-drift":
      return normalizeStyleDriftParams(query);
    case "risk-timeseries":
      return normalizeRiskTimeseriesParams(query);
    case "entity-analytics":
      return normalizeEntityAnalyticsParams(query);
    case "active-share":
      return normalizeActiveShareParams(query);
  }
}

export function normalizeFundResourceParamsFromSearch(
  resource: FundDossierSubresource,
  searchParams: URLSearchParams,
) {
  return normalizeFundResourceParams(resource, {
    range: searchParam(searchParams, "range"),
    bars: searchParam(searchParams, "bars"),
    window: searchParam(searchParams, "window"),
    limit: searchParam(searchParams, "limit"),
    quarters: searchParam(searchParams, "quarters"),
    from: searchParam(searchParams, "from"),
    to: searchParam(searchParams, "to"),
    benchmark_id: searchParam(searchParams, "benchmark_id"),
  });
}

function appendQuery(path: string, pairs: readonly (readonly [string, QueryValue])[]): string {
  const params = new URLSearchParams();
  for (const [key, value] of pairs) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function fundPath(instrumentId: string, suffix = ""): string {
  return `/funds/${encodeURIComponent(instrumentId)}${suffix}`;
}

function fundProxyPath(instrumentId: string, resource: FundDossierSubresource): string {
  return `/api/funds/${encodeURIComponent(instrumentId)}/${resource}`;
}

function paramPairs(resource: FundDossierSubresource, params: Record<string, QueryValue>) {
  switch (resource) {
    case "profile":
    case "factors":
    case "institutional-reveal":
      return [];
    case "timeseries":
      return [["range", params.range]] as const;
    case "history":
      return [["bars", params.bars]] as const;
    case "analysis":
      return [
        ["range", params.range],
        ["window", params.window],
      ] as const;
    case "holdings-top":
      return [["limit", params.limit]] as const;
    case "peers":
      return [["limit", params.limit]] as const;
    case "style-drift":
      return [["quarters", params.quarters]] as const;
    case "risk-timeseries":
      return [
        ["from", params.from],
        ["to", params.to],
      ] as const;
    case "entity-analytics":
      return [
        ["window", params.window],
        ["benchmark_id", params.benchmark_id],
      ] as const;
    case "active-share":
      return [["benchmark_id", params.benchmark_id]] as const;
  }
}

export function buildFundBackendPath(
  resource: FundDossierSubresource,
  instrumentId: string,
  params: Record<string, QueryValue> = {},
): string {
  const normalized = normalizeFundResourceParams(resource, params);
  switch (resource) {
    case "profile":
      return fundPath(instrumentId);
    case "timeseries":
      return appendQuery(fundPath(instrumentId, "/timeseries"), paramPairs(resource, normalized));
    case "history":
      return appendQuery(fundPath(instrumentId, "/history"), paramPairs(resource, normalized));
    case "analysis":
      return appendQuery(fundPath(instrumentId, "/analysis"), paramPairs(resource, normalized));
    case "holdings-top":
      return appendQuery(fundPath(instrumentId, "/holdings/top"), paramPairs(resource, normalized));
    case "peers":
      return appendQuery(fundPath(instrumentId, "/peers"), paramPairs(resource, normalized));
    case "factors":
      return fundPath(instrumentId, "/factors");
    case "style-drift":
      return appendQuery(fundPath(instrumentId, "/style-drift"), paramPairs(resource, normalized));
    case "risk-timeseries":
      return appendQuery(fundPath(instrumentId, "/risk-timeseries"), paramPairs(resource, normalized));
    case "entity-analytics":
      return appendQuery(fundPath(instrumentId, "/entity-analytics"), paramPairs(resource, normalized));
    case "active-share":
      return appendQuery(fundPath(instrumentId, "/active-share"), paramPairs(resource, normalized));
    case "institutional-reveal":
      return fundPath(instrumentId, "/institutional-reveal");
  }
}

export function buildFundProxyPath(
  resource: FundDossierSubresource,
  instrumentId: string,
  params: Record<string, QueryValue> = {},
): string {
  const normalized = normalizeFundResourceParams(resource, params);
  return appendQuery(fundProxyPath(instrumentId, resource), paramPairs(resource, normalized));
}

export function buildFundsScatterBackendPath(
  params: FundsScatterQuery | { limit?: QueryValue } = {},
): string {
  const normalized = normalizeScatterParams(params);
  return appendQuery("/funds/scatter", [["limit", normalized.limit]]);
}

export function buildFundsScatterProxyPath(
  params: FundsScatterQuery | { limit?: QueryValue } = {},
): string {
  const normalized = normalizeScatterParams(params);
  return appendQuery("/api/funds/scatter", [["limit", normalized.limit]]);
}

export function normalizeCusip(value: QueryValue): string {
  return stringParam(value, "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function buildHoldingReverseLookupBackendPath(cusip: QueryValue): string {
  return `/holdings/${encodeURIComponent(normalizeCusip(cusip))}/reverse-lookup`;
}

export function buildHoldingReverseLookupProxyPath(cusip: QueryValue): string {
  return `/api/holdings/${encodeURIComponent(normalizeCusip(cusip))}/reverse-lookup`;
}

export function fundResourceTags(resource: FundDossierSubresource, instrumentId: string): string[] {
  return [`fund:${instrumentId}`, `fund:${instrumentId}:${resource}`];
}

export function scatterTags(): string[] {
  return ["funds:scatter"];
}

export function holdingReverseLookupTags(cusip: QueryValue): string[] {
  return [`holding:${normalizeCusip(cusip)}:reverse-lookup`];
}

export function cacheKeyParts(
  resource: FundsDossierResource,
  id: string,
  pairs: readonly (readonly [string, QueryValue])[],
): string[] {
  const version = resource === "timeseries" ? [`version:${FUND_TIMESERIES_CACHE_VERSION}`] : [];
  return [
    "fund-dossier",
    resource,
    ...version,
    id,
    ...pairs.map(([key, value]) => `${key}:${value ?? "null"}`),
  ];
}

export function fundResourceCacheKey(
  resource: FundDossierSubresource,
  instrumentId: string,
  params: Record<string, QueryValue> = {},
): string[] {
  const normalized = normalizeFundResourceParams(resource, params);
  return cacheKeyParts(resource, instrumentId, paramPairs(resource, normalized));
}

export function scatterCacheKey(params = normalizeScatterParams()): string[] {
  return cacheKeyParts("scatter", "all", [["limit", params.limit]]);
}

export function holdingReverseLookupCacheKey(cusip: QueryValue): string[] {
  return cacheKeyParts("holding-reverse-lookup", normalizeCusip(cusip), []);
}

export function cacheControlHeader(resource: FundsDossierResource): string {
  const tier = CACHE_TIER_BY_RESOURCE[resource];
  return `public, s-maxage=${CACHE_SECONDS_BY_TIER[tier]}, stale-while-revalidate=${SWR_SECONDS_BY_TIER[tier]}`;
}

export function parseFundSubresource(value: string): FundDossierSubresource | null {
  switch (value) {
    case "profile":
    case "timeseries":
    case "history":
    case "analysis":
    case "holdings-top":
    case "peers":
    case "factors":
    case "style-drift":
    case "risk-timeseries":
    case "entity-analytics":
    case "active-share":
    case "institutional-reveal":
      return value;
    default:
      return null;
  }
}

export const dossierQueryKeys = {
  profile: (instrumentId: string) => ["fund-profile", instrumentId] as const,
  timeseries: (instrumentId: string, query: { range?: QueryValue } = {}) => {
    const params = normalizeTimeseriesParams(query);
    return ["fund-timeseries", FUND_TIMESERIES_CACHE_VERSION, instrumentId, params.range] as const;
  },
  history: (instrumentId: string, query: { bars?: QueryValue } = {}) => {
    const params = normalizeHistoryParams(query);
    return ["fund-history", instrumentId, params.bars] as const;
  },
  analysis: (instrumentId: string, query: FundAnalysisQuery | { range?: QueryValue; window?: QueryValue } = {}) => {
    const params = normalizeAnalysisParams(query);
    return ["fund-analysis", instrumentId, params.range, params.window] as const;
  },
  holdingsTop: (instrumentId: string, query: FundHoldingsTopQuery | { limit?: QueryValue } = {}) => {
    const params = normalizeHoldingsTopParams(query);
    return ["fund-holdings-top", instrumentId, params.limit] as const;
  },
  peers: (instrumentId: string, query: FundPeersQuery | { limit?: QueryValue } = {}) => {
    const params = normalizePeersParams(query);
    return ["fund-peers", instrumentId, params.limit] as const;
  },
  scatter: (query: FundsScatterQuery | { limit?: QueryValue } = {}) => {
    const params = normalizeScatterParams(query);
    return ["funds-scatter", params.limit] as const;
  },
  factors: (instrumentId: string) => ["fund-factors", instrumentId] as const,
  styleDrift: (instrumentId: string, query: FundStyleDriftQuery | { quarters?: QueryValue } = {}) => {
    const params = normalizeStyleDriftParams(query);
    return ["fund-style-drift", instrumentId, params.quarters] as const;
  },
  riskTimeseries: (instrumentId: string, query: FundRiskTimeseriesQuery | { from?: QueryValue; to?: QueryValue } = {}) => {
    const params = normalizeRiskTimeseriesParams(query);
    return ["fund-risk-timeseries", instrumentId, params.from, params.to] as const;
  },
  entityAnalytics: (
    instrumentId: string,
    query: FundEntityAnalyticsQuery | { window?: QueryValue; benchmark_id?: QueryValue } = {},
  ) => {
    const params = normalizeEntityAnalyticsParams(query);
    return ["fund-entity-analytics", instrumentId, params.window, params.benchmark_id] as const;
  },
  activeShare: (instrumentId: string, query: FundActiveShareQuery | { benchmark_id?: QueryValue } = {}) => {
    const params = normalizeActiveShareParams(query);
    return ["fund-active-share", instrumentId, params.benchmark_id] as const;
  },
  institutionalReveal: (instrumentId: string) => ["fund-institutional-reveal", instrumentId] as const,
  holdingReverseLookup: (cusip: QueryValue) => ["holding-reverse-lookup", normalizeCusip(cusip)] as const,
} as const;
