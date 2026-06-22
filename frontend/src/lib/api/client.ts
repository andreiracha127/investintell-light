/**
 * Typed API client — thin fetch wrapper over the backend OpenAPI contract.
 *
 * All request/response shapes derive from the generated `api.d.ts` (`paths`).
 * Errors fail loud: a non-OK response throws `ApiError` carrying the backend
 * `detail`, which the UI renders verbatim. No silent fallbacks.
 */
import type { components, paths } from "@/lib/api/api";
import { getAccessToken, refreshSession } from "@/lib/auth/token";
import {
  buildFundProxyPath,
  buildFundsScatterProxyPath,
  buildHoldingReverseLookupProxyPath,
} from "@/lib/funds/dossierQueries";

type AnalysisOperation = paths["/stocks/{ticker}/analysis"]["get"];
type PricesOperation = paths["/stocks/{ticker}/prices"]["get"];
type NewsOperation = paths["/stocks/{ticker}/news"]["get"];
type PortfolioAnalysisOperation = paths["/portfolio/analysis"]["post"];
type PortfoliosPath = paths["/portfolios"];
type PortfolioPath = paths["/portfolios/{portfolio_id}"];
type PositionPath = paths["/portfolios/{portfolio_id}/positions/{ticker}"];
type OverviewOperation = paths["/portfolios/{portfolio_id}/overview"]["get"];
type PortfolioNewsOperation = paths["/portfolios/{portfolio_id}/news"]["get"];
type PortfolioTransactionsOperation =
  paths["/portfolios/{portfolio_id}/transactions"]["get"];
type PortfolioTransactionCreateOperation =
  paths["/portfolios/{portfolio_id}/transactions"]["post"];
type PortfolioNavOperation = paths["/portfolios/{portfolio_id}/nav"]["get"];
type ScenarioOperation = paths["/statistics/scenario"]["post"];
type BetaOperation = paths["/statistics/beta"]["post"];
type CorrelationOperation = paths["/statistics/correlation"]["post"];
type StockCorrelationOperation = paths["/statistics/stock-correlation"]["post"];
type MetricCatalogOperation = paths["/screener/metrics"]["get"];
type ScreensPath = paths["/screener/screens"];
type ScreenPath = paths["/screener/screens/{screen_id}"];
type ScreenFilterPath = paths["/screener/screens/{screen_id}/filters/{metric_code}"];
type ScreenBuildOperation =
  paths["/screener/screens/{screen_id}/build/{metric_code}"]["get"];
type ScreenBuildAllOperation = paths["/screener/screens/{screen_id}/build"]["get"];
type ScreenReorderOperation = paths["/screener/screens/{screen_id}/filters/reorder"]["patch"];
type ScreenResultsOperation = paths["/screener/screens/{screen_id}/results"]["get"];
type ScreenResultsCsvOperation =
  paths["/screener/screens/{screen_id}/results.csv"]["get"];
type FundsOperation = paths["/funds"]["get"];
type BuilderOptimizeOperation = paths["/builder/optimize"]["post"];
type BacktestWalkForwardOperation = paths["/backtest/walk-forward"]["post"];
type PortfolioMonteCarloOperation = paths["/monte-carlo/portfolio"]["post"];
type BuilderSaveOperation = paths["/builder/save"]["post"];
type FundsCsvOperation = paths["/funds.csv"]["get"];
type FundProfileOperation = paths["/funds/{instrument_id}"]["get"];
type FundAnalysisOperation = paths["/funds/{instrument_id}/analysis"]["get"];
type FundHoldingsTopOperation =
  paths["/funds/{instrument_id}/holdings/top"]["get"];
type FundPeersOperation = paths["/funds/{instrument_id}/peers"]["get"];
type FundsScatterOperation = paths["/funds/scatter"]["get"];
type FundFactorsOperation = paths["/funds/{instrument_id}/factors"]["get"];
type FundStyleDriftOperation =
  paths["/funds/{instrument_id}/style-drift"]["get"];
type FundEntityAnalyticsOperation =
  paths["/funds/{instrument_id}/entity-analytics"]["get"];
type FundRiskTimeseriesOperation =
  paths["/funds/{instrument_id}/risk-timeseries"]["get"];
type FundActiveShareOperation =
  paths["/funds/{instrument_id}/active-share"]["get"];
type FundInstitutionalRevealOperation =
  paths["/funds/{instrument_id}/institutional-reveal"]["get"];
type HoldingReverseLookupOperation =
  paths["/holdings/{cusip}/reverse-lookup"]["get"];
type FundLookthroughOperation =
  paths["/funds/{instrument_id}/lookthrough"]["get"];
type PortfolioLookthroughOperation =
  paths["/portfolios/{portfolio_id}/lookthrough"]["get"];
type MacroRegimeOperation = paths["/macro/regime"]["get"];
type RebalancePolicyOperation =
  paths["/portfolios/{portfolio_id}/rebalance/policy"]["get"];
type RebalancePreviewOperation =
  paths["/portfolios/{portfolio_id}/rebalance/preview"]["get"];

type MarketOverviewOperation = paths["/stocks/overview"]["get"];
export type MarketOverview =
  MarketOverviewOperation["responses"]["200"]["content"]["application/json"];
export type LeaderRow = MarketOverview["gainers"][number];
export type IndexCard = MarketOverview["indices"][number];
export type SectorPerf = MarketOverview["sectors"][number];
export type MarketBreadth = NonNullable<MarketOverview["breadth"]>;

type StockHistoryOperation = paths["/stocks/{ticker}/history"]["get"];
export type StockHistory =
  StockHistoryOperation["responses"]["200"]["content"]["application/json"];
export type HistoryBar = StockHistory["bars"][number];

type StockTimeseriesOperation = paths["/stocks/{ticker}/timeseries"]["get"];
export type StockTimeseries =
  StockTimeseriesOperation["responses"]["200"]["content"]["application/json"];
export type StockTimeseriesQuery = NonNullable<
  StockTimeseriesOperation["parameters"]["query"]
>;

type FundHistoryOperation = paths["/funds/{instrument_id}/history"]["get"];
export type FundHistory =
  FundHistoryOperation["responses"]["200"]["content"]["application/json"];

type FundTimeseriesOperation =
  paths["/funds/{instrument_id}/timeseries"]["get"];
export type FundTimeseries =
  FundTimeseriesOperation["responses"]["200"]["content"]["application/json"];
export type FundTimeseriesQuery = NonNullable<
  FundTimeseriesOperation["parameters"]["query"]
>;
export type TimeseriesInterval = StockTimeseries["interval"];

type SymbolSearchOperation = paths["/search/symbols"]["get"];
export type SymbolSearchResult =
  SymbolSearchOperation["responses"]["200"]["content"]["application/json"][number];

export type StockAnalysis =
  AnalysisOperation["responses"]["200"]["content"]["application/json"];
export type AnalysisQuery = NonNullable<AnalysisOperation["parameters"]["query"]>;
export type RangePreset = NonNullable<AnalysisQuery["range"]>;
export type PriceSeries =
  PricesOperation["responses"]["200"]["content"]["application/json"];
export type TickerNews =
  NewsOperation["responses"]["200"]["content"]["application/json"];
export type NewsArticle = TickerNews["items"][number];

export type PortfolioAnalysisRequest =
  PortfolioAnalysisOperation["requestBody"]["content"]["application/json"];
export type PortfolioAnalysis =
  PortfolioAnalysisOperation["responses"]["200"]["content"]["application/json"];
export type PortfolioMode = PortfolioAnalysisRequest["mode"];
export type AllocationPosition =
  PortfolioAnalysis["allocation"]["positions"][number];
export type CorrelationMatrix = PortfolioAnalysis["correlation_matrix"];
export type RiskContribution = PortfolioAnalysis["risk_contributions"][number];

export type PortfolioListItem =
  PortfoliosPath["get"]["responses"]["200"]["content"]["application/json"][number];
export type PortfolioCreateRequest =
  PortfoliosPath["post"]["requestBody"]["content"]["application/json"];
export type Portfolio =
  PortfoliosPath["post"]["responses"]["201"]["content"]["application/json"];
export type PortfolioPatchRequest =
  PortfolioPath["patch"]["requestBody"]["content"]["application/json"];
export type PositionBody =
  PositionPath["put"]["requestBody"]["content"]["application/json"];
export type PositionOut =
  PositionPath["put"]["responses"]["200"]["content"]["application/json"];
export type PortfolioOverview =
  OverviewOperation["responses"]["200"]["content"]["application/json"];
export type OverviewPosition = PortfolioOverview["positions"][number];
export type OverviewAggregates = PortfolioOverview["aggregates"];
export type PortfolioNews =
  PortfolioNewsOperation["responses"]["200"]["content"]["application/json"];
export type PortfolioTransaction =
  PortfolioTransactionsOperation["responses"]["200"]["content"]["application/json"][number];
export type PortfolioTransactionBody =
  PortfolioTransactionCreateOperation["requestBody"]["content"]["application/json"];
export type PortfolioNav =
  PortfolioNavOperation["responses"]["200"]["content"]["application/json"];
export type PortfolioNavPoint = PortfolioNav["points"][number];
export type PortfolioNavQuery = NonNullable<
  PortfolioNavOperation["parameters"]["query"]
>;

export type ScenarioRequest =
  ScenarioOperation["requestBody"]["content"]["application/json"];
export type ScenarioResponse =
  ScenarioOperation["responses"]["200"]["content"]["application/json"];
export type StackedSeries = ScenarioResponse["nav_cash"][number];
export type BetaRequest =
  BetaOperation["requestBody"]["content"]["application/json"];
export type BetaResponse =
  BetaOperation["responses"]["200"]["content"]["application/json"];
/** Discriminated pseudo-asset reference: a ticker or a persisted portfolio. */
export type AssetRef = BetaRequest["asset_x"];
export type CorrelationRequest =
  CorrelationOperation["requestBody"]["content"]["application/json"];
export type CorrelationResponse =
  CorrelationOperation["responses"]["200"]["content"]["application/json"];
export type StockCorrelationRequest =
  StockCorrelationOperation["requestBody"]["content"]["application/json"];
export type StockCorrelationResponse =
  StockCorrelationOperation["responses"]["200"]["content"]["application/json"];

export type MetricDef =
  MetricCatalogOperation["responses"]["200"]["content"]["application/json"][number];
export type PresetBand = MetricDef["presets"][number];
export type ScreenListItem =
  ScreensPath["get"]["responses"]["200"]["content"]["application/json"][number];
export type ScreenCreateRequest =
  ScreensPath["post"]["requestBody"]["content"]["application/json"];
export type Screen =
  ScreensPath["post"]["responses"]["201"]["content"]["application/json"];
export type ScreenFilter = Screen["filters"][number];
export type ScreenPatchRequest =
  ScreenPath["patch"]["requestBody"]["content"]["application/json"];
export type FilterBody =
  ScreenFilterPath["put"]["requestBody"]["content"]["application/json"];
export type FilterUpdateResponse =
  ScreenFilterPath["put"]["responses"]["200"]["content"]["application/json"];
export type Distribution = NonNullable<FilterUpdateResponse["distribution"]>;
export type BuildResponse =
  ScreenBuildOperation["responses"]["200"]["content"]["application/json"];
export type BuildAll =
  ScreenBuildAllOperation["responses"]["200"]["content"]["application/json"];
export type MetricBuild = BuildAll["metrics"][number];
export type FilterReorderBody =
  ScreenReorderOperation["requestBody"]["content"]["application/json"];
export type ScreenResults =
  ScreenResultsOperation["responses"]["200"]["content"]["application/json"];
export type ResultsColumn = ScreenResults["columns"][number];
export type ResultsRow = ScreenResults["rows"][number];
export type ResultsQuery = NonNullable<
  ScreenResultsOperation["parameters"]["query"]
>;
export type ResultsCsvQuery = NonNullable<
  ScreenResultsCsvOperation["parameters"]["query"]
>;

export type FundsList =
  FundsOperation["responses"]["200"]["content"]["application/json"];
export type FundListItem = FundsList["items"][number];
export type FundsStaleness = FundsList["staleness"];
export type FundsQuery = NonNullable<FundsOperation["parameters"]["query"]>;
export type FundsCsvQuery = NonNullable<FundsCsvOperation["parameters"]["query"]>;
export type FundProfile =
  FundProfileOperation["responses"]["200"]["content"]["application/json"];
export type FundRisk = NonNullable<FundProfile["risk"]>;
export type FundNavPoint = FundProfile["nav"][number];
export type FundHolding = FundProfile["holdings"]["items"][number];
export type FundAnalysis =
  FundAnalysisOperation["responses"]["200"]["content"]["application/json"];
export type FundAnalysisQuery = NonNullable<
  FundAnalysisOperation["parameters"]["query"]
>;
export type FundHoldingsTop =
  FundHoldingsTopOperation["responses"]["200"]["content"]["application/json"];
export type FundHoldingsTopQuery = NonNullable<
  FundHoldingsTopOperation["parameters"]["query"]
>;
export type FundPeers =
  FundPeersOperation["responses"]["200"]["content"]["application/json"];
export type FundPeersQuery = NonNullable<FundPeersOperation["parameters"]["query"]>;
export type FundsScatter =
  FundsScatterOperation["responses"]["200"]["content"]["application/json"];
export type FundsScatterQuery = NonNullable<
  FundsScatterOperation["parameters"]["query"]
>;
export type FundFactors =
  FundFactorsOperation["responses"]["200"]["content"]["application/json"];
export type FundStyleDrift =
  FundStyleDriftOperation["responses"]["200"]["content"]["application/json"];
export type FundStyleDriftQuery = NonNullable<
  FundStyleDriftOperation["parameters"]["query"]
>;
export type FundEntityAnalytics =
  FundEntityAnalyticsOperation["responses"]["200"]["content"]["application/json"];
export type FundEntityAnalyticsQuery = NonNullable<
  FundEntityAnalyticsOperation["parameters"]["query"]
>;
export type FundRiskTimeseries =
  FundRiskTimeseriesOperation["responses"]["200"]["content"]["application/json"];
export type FundRiskTimeseriesQuery = NonNullable<
  FundRiskTimeseriesOperation["parameters"]["query"]
>;
export type FundActiveShare =
  FundActiveShareOperation["responses"]["200"]["content"]["application/json"];
export type FundActiveShareQuery = NonNullable<
  FundActiveShareOperation["parameters"]["query"]
>;
export type FundInstitutionalReveal =
  FundInstitutionalRevealOperation["responses"]["200"]["content"]["application/json"];
export type HoldingReverseLookup =
  HoldingReverseLookupOperation["responses"]["200"]["content"]["application/json"];

export type FundLookthroughQuery = NonNullable<
  FundLookthroughOperation["parameters"]["query"]
>;
export type FundLookthrough =
  FundLookthroughOperation["responses"]["200"]["content"]["application/json"];
export type PortfolioLookthrough =
  PortfolioLookthroughOperation["responses"]["200"]["content"]["application/json"];
export type ExposureItem = components["schemas"]["ExposureItem"];
export type LookthroughSummary = components["schemas"]["LookthroughSummaryOut"];
export type MacroRegime =
  MacroRegimeOperation["responses"]["200"]["content"]["application/json"];
export type RegimeSignal = components["schemas"]["RegimeSignalOut"];
export type RegimeFlip = components["schemas"]["RegimeFlipOut"];
export type RebalancePolicy =
  RebalancePolicyOperation["responses"]["200"]["content"]["application/json"];
export type RebalancePreview =
  RebalancePreviewOperation["responses"]["200"]["content"]["application/json"];
export type PositionDrift = components["schemas"]["PositionDriftOut"];
export type Proposal = components["schemas"]["ProposalOut"];

export type OptimizeRequest =
  BuilderOptimizeOperation["requestBody"]["content"]["application/json"];
export type OptimizeResponse =
  BuilderOptimizeOperation["responses"]["200"]["content"]["application/json"];
export type WalkForwardRequest =
  BacktestWalkForwardOperation["requestBody"]["content"]["application/json"];
export type WalkForwardResponse =
  BacktestWalkForwardOperation["responses"]["200"]["content"]["application/json"];
export type FoldMetrics = WalkForwardResponse["folds"][number];
export type PortfolioMonteCarloRequest =
  PortfolioMonteCarloOperation["requestBody"]["content"]["application/json"];
export type PortfolioMonteCarloResponse =
  PortfolioMonteCarloOperation["responses"]["200"]["content"]["application/json"];
export type ConfidenceBar = PortfolioMonteCarloResponse["confidence_bars"][number];
export type MonteCarloStatistic = PortfolioMonteCarloRequest["statistic"];
/** Discriminated asset reference: a synced fund (uuid) or an equity ticker. */
export type BuilderAssetRef = NonNullable<OptimizeRequest["assets"]>[number];
/** Filter+rank spec to optimize over the fund universe (no explicit list). */
export type BuilderUniverseSpec = NonNullable<OptimizeRequest["universe"]>;
export type BuilderObjective = OptimizeRequest["objective"];
export type BuilderViewIn = NonNullable<OptimizeRequest["views"]>[number];
export type WeightOut = OptimizeResponse["weights"][number];
export type BuilderDiagnostics = OptimizeResponse["diagnostics"];
export type BuilderSaveRequest =
  BuilderSaveOperation["requestBody"]["content"]["application/json"];
export type BuilderSaveResponse =
  BuilderSaveOperation["responses"]["201"]["content"]["application/json"];

export type Candle = StockAnalysis["candles"][number];
export type CumulativeReturns = StockAnalysis["cumulative_returns"];
export type Histogram = StockAnalysis["histogram"];
export type SeriesPoint = [string, number];

export const RANGE_PRESETS = [
  "1M",
  "6M",
  "1Y",
  "5Y",
  "MAX",
] as const satisfies readonly RangePreset[];

export function isRangePreset(value: unknown): value is RangePreset {
  return (
    typeof value === "string" && (RANGE_PRESETS as readonly string[]).includes(value)
  );
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function backendRequestUrl(path: string): string {
  if (typeof window !== "undefined") return `/api/backend${path}`;
  return `${BASE_URL}${path}`;
}

type AuthFetchDeps = {
  getToken: () => string | null;
  refresh: () => Promise<boolean>;
  onAuthFail: () => void;
  fetchImpl: typeof fetch;
};

/** Wrap fetch: attach Bearer from the readable cookie; on 401/403 refresh once
 *  and retry; on persistent auth failure call onAuthFail and return the response. */
export function createFetchWithAuth(deps: AuthFetchDeps) {
  const { getToken, refresh, onAuthFail, fetchImpl } = deps;
  return async function fetchWithAuth(
    input: RequestInfo | URL,
    init: RequestInit = {},
  ): Promise<Response> {
    const withAuth = (token: string | null): RequestInit => {
      const base: Record<string, string> =
        init.headers instanceof Headers
          ? Object.fromEntries(init.headers.entries())
          : Array.isArray(init.headers)
            ? Object.fromEntries(init.headers as [string, string][])
            : { ...(init.headers as Record<string, string> | undefined) };
      if (token) base["Authorization"] = `Bearer ${token}`;
      // The FastAPI backend authenticates via the Bearer header, not cookies.
      // Do NOT send credentials cross-origin: it would force a credentialed
      // CORS response (Access-Control-Allow-Credentials) the API does not set,
      // blocking every call. Same-origin /api/auth/* keep their own credentials.
      return { ...init, headers: base };
    };

    let res = await fetchImpl(input, withAuth(getToken()));
    if (res.status === 401 || res.status === 403) {
      const refreshed = await refresh();
      if (refreshed) {
        res = await fetchImpl(input, withAuth(getToken()));
      }
      if (res.status === 401 || res.status === 403) {
        onAuthFail();
      }
    }
    return res;
  };
}

const fetchWithAuth = createFetchWithAuth({
  getToken: getAccessToken,
  refresh: () => refreshSession(),
  onAuthFail: () => {
    if (typeof window !== "undefined") {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
  },
  fetchImpl: (input, init) => fetch(input, init),
});

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Extract the backend `detail` from an error body, else a status fallback.
 *
 * Pydantic 422 bodies send `detail` as an array of `{msg, loc, ...}` objects.
 * Stringifying those raw arrays produces unreadable JSON; instead we map each
 * entry to "<field>: <message>" and join with newlines for readable UI output.
 */
function extractDetail(body: unknown, fallback: string): string {
  if (body !== null && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      // Pydantic-style: [{msg: string, loc: string[], ...}, ...]
      const isPydanticEntry = (e: unknown): e is { msg: string; loc: string[] } =>
        e !== null &&
        typeof e === "object" &&
        "msg" in e &&
        typeof (e as Record<string, unknown>).msg === "string" &&
        "loc" in e &&
        Array.isArray((e as Record<string, unknown>).loc);

      if (detail.every(isPydanticEntry)) {
        return detail
          .map((e) => {
            // loc[0] is always "body"; drop it for a cleaner field path.
            const field = e.loc.slice(1).join(".");
            return field ? `${field}: ${e.msg}` : e.msg;
          })
          .join("\n");
      }
      // Non-Pydantic array — fall back to JSON so nothing is silently lost.
      return JSON.stringify(detail);
    }
    if (detail !== undefined) return JSON.stringify(detail);
  }
  return fallback;
}

async function request<T>(
  path: string,
  signal?: AbortSignal,
  init?: { method: "POST" | "PUT" | "PATCH" | "DELETE"; json?: unknown },
  authMode: "auth" | "public" = "auth",
): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(15_000);
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal;
  const fetcher = authMode === "public" ? fetch : fetchWithAuth;

  let res: Response;
  try {
    res = await fetcher(backendRequestUrl(path), {
      signal: combinedSignal,
      ...(init && {
        method: init.method,
        ...(init.json !== undefined && {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(init.json),
        }),
      }),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // Distinguish a timeout from a caller-triggered abort (e.g. unmount).
      if (timeoutSignal.aborted) {
        throw new Error("Request timed out — is the backend running?");
      }
      throw new Error("Request cancelled");
    }
    throw err;
  }

  if (!res.ok) {
    const fallback = `HTTP ${res.status} ${res.statusText}`.trim();
    let detail = fallback;
    try {
      detail = extractDetail(await res.json(), fallback);
    } catch {
      // Non-JSON error body — keep the HTTP status as the message.
    }
    throw new ApiError(res.status, detail);
  }
  // DELETE endpoints respond 204 with no body — there is nothing to parse.
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function requestPublic<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, signal, undefined, "public");
}

async function requestSameOrigin<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(15_000);
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal;

  let res: Response;
  try {
    res = await fetch(path, {
      signal: combinedSignal,
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      if (timeoutSignal.aborted) {
        throw new Error("Request timed out — is the backend running?");
      }
      throw new Error("Request cancelled");
    }
    throw err;
  }

  if (!res.ok) {
    const fallback = `HTTP ${res.status} ${res.statusText}`.trim();
    let detail = fallback;
    try {
      detail = extractDetail(await res.json(), fallback);
    } catch {
      // Non-JSON error body — keep the HTTP status as the message.
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function postPortfolioAnalysis(
  body: PortfolioAnalysisRequest,
  signal?: AbortSignal,
): Promise<PortfolioAnalysis> {
  return request<PortfolioAnalysis>("/portfolio/analysis", signal, {
    method: "POST",
    json: body,
  });
}

export function fetchStockAnalysis(
  ticker: string,
  query: AnalysisQuery = {},
  signal?: AbortSignal,
): Promise<StockAnalysis> {
  const params = new URLSearchParams();
  if (query.range !== undefined) params.set("range", query.range);
  if (query.benchmark !== undefined) params.set("benchmark", query.benchmark);
  if (query.window !== undefined) params.set("window", String(query.window));
  const qs = params.toString();
  return request<StockAnalysis>(
    `/stocks/${encodeURIComponent(ticker)}/analysis${qs ? `?${qs}` : ""}`,
    signal,
  );
}

export function fetchMarketOverview(signal?: AbortSignal): Promise<MarketOverview> {
  return requestPublic<MarketOverview>("/stocks/overview", signal);
}

export function fetchStockHistory(
  ticker: string,
  bars = 2520,
  signal?: AbortSignal,
): Promise<StockHistory> {
  return request<StockHistory>(
    `/stocks/${encodeURIComponent(ticker)}/history?bars=${bars}`,
    signal,
  );
}

export function fetchStockTimeseries(
  ticker: string,
  range: RangePreset,
  signal?: AbortSignal,
): Promise<StockTimeseries> {
  return request<StockTimeseries>(
    `/stocks/${encodeURIComponent(ticker)}/timeseries?range=${range}`,
    signal,
  );
}

/** One 13F institutional holder of a stock (Stocks → Holders tab). */
export interface StockHolder {
  cik: string;
  manager_name: string;
  shares: number | null;
  market_value: number | null;
  /** Stake as a fraction of shares outstanding (0.079 = 7.9% owned). */
  pct_outstanding: number | null;
  /** Price return from the holder's entry quarter to today (decimal fraction). */
  position_return: number | null;
  entry_date: string | null;
}

export interface StockHolders {
  ticker: string;
  cusip: string | null;
  security_name: string | null;
  period: string | null;
  holder_count: number;
  total_market_value: number | null;
  shares_outstanding: number | null;
  holders: StockHolder[];
  empty_state: { reason: string; source: string | null } | null;
}

export function fetchStockHolders(
  ticker: string,
  signal?: AbortSignal,
): Promise<StockHolders> {
  return request<StockHolders>(
    `/stocks/${encodeURIComponent(ticker)}/holders`,
    signal,
  );
}

/** One registered fund (N-PORT series) holding the stock. */
export interface FundHolder {
  series_id: string;
  fund_name: string;
  /** Light-catalog instrument id for the fund dossier link (null if uncatalogued). */
  instrument_id: string | null;
  quantity: number | null;
  market_value: number | null;
  /** Percent of the fund's NAV in this stock (percent points, 15.6 = 15.6%).
   *  pct_of_nav is the latest quarter (Q0); q1..q3 are the three prior quarters. */
  pct_of_nav: number | null;
  pct_nav_q1: number | null;
  pct_nav_q2: number | null;
  pct_nav_q3: number | null;
}

/** A registrant/trust grouping its funds that hold the stock (tree parent). */
export interface FundFamily {
  registrant_cik: string;
  family: string;
  market_value: number | null;
  fund_count: number;
  funds: FundHolder[];
}

export interface StockFundHolders {
  ticker: string;
  cusip: string | null;
  security_name: string | null;
  period: string | null;
  family_count: number;
  fund_count: number;
  total_market_value: number | null;
  families: FundFamily[];
  empty_state: { reason: string; source: string | null } | null;
}

export function fetchStockFundHolders(
  ticker: string,
  signal?: AbortSignal,
): Promise<StockFundHolders> {
  return request<StockFundHolders>(
    `/stocks/${encodeURIComponent(ticker)}/holders/funds`,
    signal,
  );
}

export function fetchFundHistory(
  instrumentId: string,
  bars = 2520,
  signal?: AbortSignal,
): Promise<FundHistory> {
  return requestSameOrigin<FundHistory>(
    buildFundProxyPath("history", instrumentId, { bars }),
    signal,
  );
}

export function fetchFundTimeseries(
  instrumentId: string,
  range: RangePreset,
  signal?: AbortSignal,
): Promise<FundTimeseries> {
  return requestSameOrigin<FundTimeseries>(
    buildFundProxyPath("timeseries", instrumentId, { range }),
    signal,
  );
}

/** Convert stock OHLC/volume arrays into the chart bar contract. */
export function stockTimeseriesToHistoryBars(
  data: StockTimeseries,
): HistoryBar[] {
  const volumeByTime = new Map(data.volume.map((point) => [point[0], point[1]]));
  return data.ohlc
    .filter((point) => point.length >= 5)
    .map((point) => ({
      t: point[0],
      o: point[1],
      h: point[2],
      l: point[3],
      c: point[4],
      v: volumeByTime.get(point[0]) ?? 0,
    }));
}

/** Convert fund NAV line arrays into chart bars for the Stock chart. */
export function fundTimeseriesToHistoryBars(data: FundTimeseries): HistoryBar[] {
  return data.series
    .filter((point) => point.length >= 2)
    .map((point) => ({
      t: point[0],
      o: point[1],
      h: point[1],
      l: point[1],
      c: point[1],
      v: 0,
    }));
}

export function fundTimeseriesToNavPoints(
  data: FundTimeseries,
): FundNavPoint[] {
  return data.series
    .filter((point) => point.length >= 2)
    .map((point) => ({
      date: new Date(point[0]).toISOString().slice(0, 10),
      nav: point[1],
    }));
}

export function fetchSymbolSearch(
  q: string,
  signal?: AbortSignal,
): Promise<SymbolSearchResult[]> {
  return request<SymbolSearchResult[]>(
    `/search/symbols?q=${encodeURIComponent(q)}`,
    signal,
  );
}

export function fetchTickerNews(
  ticker: string,
  query: NonNullable<NewsOperation["parameters"]["query"]> = {},
  signal?: AbortSignal,
): Promise<TickerNews> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  const qs = params.toString();
  return request<TickerNews>(
    `/stocks/${encodeURIComponent(ticker)}/news${qs ? `?${qs}` : ""}`,
    signal,
  );
}

/* ── Persisted portfolios (F4) ────────────────────────────────────────────── */

export function fetchPortfolios(
  signal?: AbortSignal,
): Promise<PortfolioListItem[]> {
  return request<PortfolioListItem[]>("/portfolios", signal);
}

export function createPortfolio(
  body: PortfolioCreateRequest,
  signal?: AbortSignal,
): Promise<Portfolio> {
  return request<Portfolio>("/portfolios", signal, {
    method: "POST",
    json: body,
  });
}

export function patchPortfolio(
  portfolioId: number,
  body: PortfolioPatchRequest,
  signal?: AbortSignal,
): Promise<Portfolio> {
  return request<Portfolio>(`/portfolios/${portfolioId}`, signal, {
    method: "PATCH",
    json: body,
  });
}

export function deletePortfolio(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<void> {
  return request<void>(`/portfolios/${portfolioId}`, signal, {
    method: "DELETE",
  });
}

export function putPosition(
  portfolioId: number,
  ticker: string,
  body: PositionBody,
  signal?: AbortSignal,
): Promise<PositionOut> {
  return request<PositionOut>(
    `/portfolios/${portfolioId}/positions/${encodeURIComponent(ticker)}`,
    signal,
    { method: "PUT", json: body },
  );
}

export function deletePosition(
  portfolioId: number,
  ticker: string,
  signal?: AbortSignal,
): Promise<void> {
  return request<void>(
    `/portfolios/${portfolioId}/positions/${encodeURIComponent(ticker)}`,
    signal,
    { method: "DELETE" },
  );
}

export function fetchPortfolioOverview(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<PortfolioOverview> {
  return request<PortfolioOverview>(
    `/portfolios/${portfolioId}/overview`,
    signal,
  );
}

export function fetchPortfolioTransactions(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<PortfolioTransaction[]> {
  return request<PortfolioTransaction[]>(
    `/portfolios/${portfolioId}/transactions`,
    signal,
  );
}

export function createPortfolioTransaction(
  portfolioId: number,
  body: PortfolioTransactionBody,
  signal?: AbortSignal,
): Promise<PortfolioTransaction> {
  return request<PortfolioTransaction>(
    `/portfolios/${portfolioId}/transactions`,
    signal,
    { method: "POST", json: body },
  );
}

export function fetchPortfolioNav(
  portfolioId: number,
  query: PortfolioNavQuery = {},
  signal?: AbortSignal,
): Promise<PortfolioNav> {
  const params = new URLSearchParams();
  if (query.end_date !== undefined) params.set("end_date", String(query.end_date));
  const qs = params.toString();
  return request<PortfolioNav>(
    `/portfolios/${portfolioId}/nav${qs ? `?${qs}` : ""}`,
    signal,
  );
}

export function fetchPortfolioNews(
  portfolioId: number,
  query: NonNullable<PortfolioNewsOperation["parameters"]["query"]> = {},
  signal?: AbortSignal,
): Promise<PortfolioNews> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  const qs = params.toString();
  return request<PortfolioNews>(
    `/portfolios/${portfolioId}/news${qs ? `?${qs}` : ""}`,
    signal,
  );
}

/* ── Statistics tools (F5) ────────────────────────────────────────────────── */

export function postScenario(
  body: ScenarioRequest,
  signal?: AbortSignal,
): Promise<ScenarioResponse> {
  return request<ScenarioResponse>("/statistics/scenario", signal, {
    method: "POST",
    json: body,
  });
}

export function postBeta(
  body: BetaRequest,
  signal?: AbortSignal,
): Promise<BetaResponse> {
  return request<BetaResponse>("/statistics/beta", signal, {
    method: "POST",
    json: body,
  });
}

export function postCorrelation(
  body: CorrelationRequest,
  signal?: AbortSignal,
): Promise<CorrelationResponse> {
  return request<CorrelationResponse>("/statistics/correlation", signal, {
    method: "POST",
    json: body,
  });
}

export function postStockCorrelation(
  body: StockCorrelationRequest,
  signal?: AbortSignal,
): Promise<StockCorrelationResponse> {
  return request<StockCorrelationResponse>(
    "/statistics/stock-correlation",
    signal,
    { method: "POST", json: body },
  );
}

/* ── Screener (F6) ────────────────────────────────────────────────────────── */

export function fetchMetricCatalog(signal?: AbortSignal): Promise<MetricDef[]> {
  return request<MetricDef[]>("/screener/metrics", signal);
}

export function fetchScreens(signal?: AbortSignal): Promise<ScreenListItem[]> {
  return request<ScreenListItem[]>("/screener/screens", signal);
}

export function createScreen(
  body: ScreenCreateRequest,
  signal?: AbortSignal,
): Promise<Screen> {
  return request<Screen>("/screener/screens", signal, {
    method: "POST",
    json: body,
  });
}

export function fetchScreen(
  screenId: number,
  signal?: AbortSignal,
): Promise<Screen> {
  return request<Screen>(`/screener/screens/${screenId}`, signal);
}

export function patchScreen(
  screenId: number,
  body: ScreenPatchRequest,
  signal?: AbortSignal,
): Promise<Screen> {
  return request<Screen>(`/screener/screens/${screenId}`, signal, {
    method: "PATCH",
    json: body,
  });
}

export function deleteScreen(
  screenId: number,
  signal?: AbortSignal,
): Promise<void> {
  return request<void>(`/screener/screens/${screenId}`, signal, {
    method: "DELETE",
  });
}

export function putScreenFilter(
  screenId: number,
  metricCode: string,
  body: FilterBody,
  signal?: AbortSignal,
): Promise<FilterUpdateResponse> {
  return request<FilterUpdateResponse>(
    `/screener/screens/${screenId}/filters/${encodeURIComponent(metricCode)}`,
    signal,
    { method: "PUT", json: body },
  );
}

export function deleteScreenFilter(
  screenId: number,
  metricCode: string,
  signal?: AbortSignal,
): Promise<FilterUpdateResponse> {
  return request<FilterUpdateResponse>(
    `/screener/screens/${screenId}/filters/${encodeURIComponent(metricCode)}`,
    signal,
    { method: "DELETE" },
  );
}

export function fetchBuildMetric(
  screenId: number,
  metricCode: string,
  signal?: AbortSignal,
): Promise<BuildResponse> {
  return request<BuildResponse>(
    `/screener/screens/${screenId}/build/${encodeURIComponent(metricCode)}`,
    signal,
  );
}

export function fetchScreenBuildAll(
  screenId: number,
  signal?: AbortSignal,
): Promise<BuildAll> {
  return request<BuildAll>(`/screener/screens/${screenId}/build`, signal);
}

export function reorderScreenFilters(
  screenId: number,
  metricCodes: string[],
): Promise<Screen> {
  return request<Screen>(
    `/screener/screens/${screenId}/filters/reorder`,
    undefined,
    { method: "PATCH", json: { metric_codes: metricCodes } satisfies FilterReorderBody },
  );
}

function resultsParams(query: ResultsQuery | ResultsCsvQuery): string {
  const params = new URLSearchParams();
  if (query.sort !== undefined) params.set("sort", query.sort);
  if (query.dir !== undefined) params.set("dir", query.dir);
  if (query.search != null && query.search !== "") {
    params.set("search", query.search);
  }
  if ("page" in query && query.page !== undefined) {
    params.set("page", String(query.page));
  }
  if ("page_size" in query && query.page_size !== undefined) {
    params.set("page_size", String(query.page_size));
  }
  return params.toString();
}

export function fetchScreenResults(
  screenId: number,
  query: ResultsQuery = {},
  signal?: AbortSignal,
): Promise<ScreenResults> {
  const qs = resultsParams(query);
  return request<ScreenResults>(
    `/screener/screens/${screenId}/results${qs ? `?${qs}` : ""}`,
    signal,
  );
}

/**
 * CSV export — raw fetch (the typed `request` helper parses JSON). Same base
 * URL and fail-loud `ApiError` semantics; resolves to a Blob for download.
 */
export async function fetchScreenResultsCsv(
  screenId: number,
  query: ResultsCsvQuery = {},
  signal?: AbortSignal,
): Promise<Blob> {
  const qs = resultsParams(query);
  const res = await fetchWithAuth(
    backendRequestUrl(`/screener/screens/${screenId}/results.csv${qs ? `?${qs}` : ""}`),
    { signal: signal ?? AbortSignal.timeout(30_000) },
  );
  if (!res.ok) {
    const fallback = `HTTP ${res.status} ${res.statusText}`.trim();
    let detail = fallback;
    try {
      detail = extractDetail(await res.json(), fallback);
    } catch {
      // Non-JSON error body — keep the HTTP status as the message.
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

/* ── Funds (F8.2) ─────────────────────────────────────────────────────────── */

function fundsParams(query: FundsQuery | FundsCsvQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  return params.toString();
}

export function fetchFunds(
  query: FundsQuery = {},
  signal?: AbortSignal,
): Promise<FundsList> {
  const qs = fundsParams(query);
  return requestPublic<FundsList>(`/funds${qs ? `?${qs}` : ""}`, signal);
}


export function fetchFundStrategies(signal?: AbortSignal): Promise<string[]> {
  return requestPublic<string[]>("/funds/strategies", signal);
}

export function fetchFundProfile(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<FundProfile> {
  return requestSameOrigin<FundProfile>(
    buildFundProxyPath("profile", instrumentId),
    signal,
  );
}

export function fetchFundAnalysis(
  instrumentId: string,
  query: FundAnalysisQuery = {},
  signal?: AbortSignal,
): Promise<FundAnalysis> {
  return requestSameOrigin<FundAnalysis>(
    buildFundProxyPath("analysis", instrumentId, query),
    signal,
  );
}

export function fetchFundHoldingsTop(
  instrumentId: string,
  query: FundHoldingsTopQuery = {},
  signal?: AbortSignal,
): Promise<FundHoldingsTop> {
  return requestSameOrigin<FundHoldingsTop>(
    buildFundProxyPath("holdings-top", instrumentId, query),
    signal,
  );
}

export function fetchFundPeers(
  instrumentId: string,
  query: FundPeersQuery = {},
  signal?: AbortSignal,
): Promise<FundPeers> {
  return requestSameOrigin<FundPeers>(
    buildFundProxyPath("peers", instrumentId, query),
    signal,
  );
}

export function fetchFundsScatter(
  query: FundsScatterQuery = {},
  signal?: AbortSignal,
): Promise<FundsScatter> {
  return requestSameOrigin<FundsScatter>(
    buildFundsScatterProxyPath(query),
    signal,
  );
}

export function fetchFundFactors(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<FundFactors> {
  return requestSameOrigin<FundFactors>(
    buildFundProxyPath("factors", instrumentId),
    signal,
  );
}

export function fetchFundStyleDrift(
  instrumentId: string,
  query: FundStyleDriftQuery = {},
  signal?: AbortSignal,
): Promise<FundStyleDrift> {
  return requestSameOrigin<FundStyleDrift>(
    buildFundProxyPath("style-drift", instrumentId, query),
    signal,
  );
}

export function fetchFundEntityAnalytics(
  instrumentId: string,
  query: FundEntityAnalyticsQuery = {},
  signal?: AbortSignal,
): Promise<FundEntityAnalytics> {
  return requestSameOrigin<FundEntityAnalytics>(
    buildFundProxyPath("entity-analytics", instrumentId, query),
    signal,
  );
}

export function fetchFundRiskTimeseries(
  instrumentId: string,
  query: FundRiskTimeseriesQuery = {},
  signal?: AbortSignal,
): Promise<FundRiskTimeseries> {
  return requestSameOrigin<FundRiskTimeseries>(
    buildFundProxyPath("risk-timeseries", instrumentId, query),
    signal,
  );
}

export function fetchFundActiveShare(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<FundActiveShare> {
  return requestSameOrigin<FundActiveShare>(
    buildFundProxyPath("active-share", instrumentId),
    signal,
  );
}

export function fetchFundInstitutionalReveal(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<FundInstitutionalReveal> {
  return requestSameOrigin<FundInstitutionalReveal>(
    buildFundProxyPath("institutional-reveal", instrumentId),
    signal,
  );
}

export function fetchHoldingReverseLookup(
  cusip: string,
  signal?: AbortSignal,
): Promise<HoldingReverseLookup> {
  return requestSameOrigin<HoldingReverseLookup>(
    buildHoldingReverseLookupProxyPath(cusip),
    signal,
  );
}

/** Funds CSV export — raw fetch (same fail-loud semantics as the screener CSV). */
export async function fetchFundsCsv(
  query: FundsCsvQuery = {},
  signal?: AbortSignal,
): Promise<Blob> {
  const qs = fundsParams(query);
  const res = await fetch(backendRequestUrl(`/funds.csv${qs ? `?${qs}` : ""}`), {
    signal: signal ?? AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const fallback = `HTTP ${res.status} ${res.statusText}`.trim();
    let detail = fallback;
    try {
      detail = extractDetail(await res.json(), fallback);
    } catch {
      // Non-JSON error body — keep the HTTP status as the message.
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

/* ── Portfolio Builder (F8.5) ─────────────────────────────────────────────── */

export function postBuilderOptimize(
  body: OptimizeRequest,
  signal?: AbortSignal,
): Promise<OptimizeResponse> {
  return request<OptimizeResponse>("/builder/optimize", signal, {
    method: "POST",
    json: body,
  });
}

export function postBacktestWalkForward(
  body: WalkForwardRequest,
  signal?: AbortSignal,
): Promise<WalkForwardResponse> {
  return request<WalkForwardResponse>("/backtest/walk-forward", signal, {
    method: "POST",
    json: body,
  });
}

export function postPortfolioMonteCarlo(
  body: PortfolioMonteCarloRequest,
  signal?: AbortSignal,
): Promise<PortfolioMonteCarloResponse> {
  return request<PortfolioMonteCarloResponse>("/monte-carlo/portfolio", signal, {
    method: "POST",
    json: body,
  });
}

export function postBuilderSave(
  body: BuilderSaveRequest,
  signal?: AbortSignal,
): Promise<BuilderSaveResponse> {
  return request<BuilderSaveResponse>("/builder/save", signal, {
    method: "POST",
    json: body,
  });
}

export function fetchPriceSeries(
  ticker: string,
  query: NonNullable<PricesOperation["parameters"]["query"]> = {},
  signal?: AbortSignal,
): Promise<PriceSeries> {
  const params = new URLSearchParams();
  if (query.start_date != null) params.set("start_date", query.start_date);
  if (query.end_date != null) params.set("end_date", query.end_date);
  const qs = params.toString();
  return request<PriceSeries>(
    `/stocks/${encodeURIComponent(ticker)}/prices${qs ? `?${qs}` : ""}`,
    signal,
  );
}

/* ── Look-through, macro regime & rebalancing ─────────────────────────────── */

/** Fetch aggregated look-through exposures for a single fund. */
export function fetchFundLookthrough(
  instrumentId: string,
  query: FundLookthroughQuery = {},
  signal?: AbortSignal,
): Promise<FundLookthrough> {
  const params = new URLSearchParams();
  if (query.dimension != null) params.set("dimension", query.dimension); // schema allows explicit null — guard both
  const qs = params.toString();
  return requestPublic<FundLookthrough>(
    `/funds/${encodeURIComponent(instrumentId)}/lookthrough${qs ? `?${qs}` : ""}`,
    signal,
  );
}

/** Fetch aggregated look-through exposures for a persisted portfolio. */
export function fetchPortfolioLookthrough(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<PortfolioLookthrough> {
  return request<PortfolioLookthrough>(
    `/portfolios/${portfolioId}/lookthrough`,
    signal,
  );
}

/** Fetch the bounded drilldown tree for portfolio look-through charts. */
export function fetchPortfolioLookthroughTree(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<PortfolioLookthrough> {
  return request<PortfolioLookthrough>(
    `/portfolios/${portfolioId}/lookthrough?include_tree=true&dimension=asset_class`,
    signal,
  );
}

/** Fetch the current macro regime signals and recent regime flips. */
export function fetchMacroRegime(signal?: AbortSignal): Promise<MacroRegime> {
  return requestPublic<MacroRegime>("/macro/regime", signal);
}

/** Fetch the rebalance policy (bands and frequency) for a portfolio. */
export function fetchRebalancePolicy(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<RebalancePolicy> {
  return request<RebalancePolicy>(
    `/portfolios/${portfolioId}/rebalance/policy`,
    signal,
  );
}

/** Fetch a dry-run rebalance preview with drift and trade proposals. */
export function fetchRebalancePreview(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<RebalancePreview> {
  return request<RebalancePreview>(
    `/portfolios/${portfolioId}/rebalance/preview`,
    signal,
  );
}
