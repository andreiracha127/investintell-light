/**
 * Typed API client — thin fetch wrapper over the backend OpenAPI contract.
 *
 * All request/response shapes derive from the generated `api.d.ts` (`paths`).
 * Errors fail loud: a non-OK response throws `ApiError` carrying the backend
 * `detail`, which the UI renders verbatim. No silent fallbacks.
 */
import type { paths } from "@/lib/api/api";

type AnalysisOperation = paths["/stocks/{ticker}/analysis"]["get"];
type PricesOperation = paths["/stocks/{ticker}/prices"]["get"];
type NewsOperation = paths["/stocks/{ticker}/news"]["get"];
type PortfolioAnalysisOperation = paths["/portfolio/analysis"]["post"];
type PortfoliosPath = paths["/portfolios"];
type PortfolioPath = paths["/portfolios/{portfolio_id}"];
type PositionPath = paths["/portfolios/{portfolio_id}/positions/{ticker}"];
type OverviewOperation = paths["/portfolios/{portfolio_id}/overview"]["get"];
type PortfolioNewsOperation = paths["/portfolios/{portfolio_id}/news"]["get"];
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
type ScreenResultsOperation = paths["/screener/screens/{screen_id}/results"]["get"];
type ScreenResultsCsvOperation =
  paths["/screener/screens/{screen_id}/results.csv"]["get"];
type FundsOperation = paths["/funds"]["get"];
type FundsCsvOperation = paths["/funds.csv"]["get"];
type FundProfileOperation = paths["/funds/{instrument_id}"]["get"];

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
): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(15_000);
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal;

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
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
  const res = await fetch(
    `${BASE_URL}/screener/screens/${screenId}/results.csv${qs ? `?${qs}` : ""}`,
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
  return request<FundsList>(`/funds${qs ? `?${qs}` : ""}`, signal);
}

export function fetchFundProfile(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<FundProfile> {
  return request<FundProfile>(
    `/funds/${encodeURIComponent(instrumentId)}`,
    signal,
  );
}

/** Funds CSV export — raw fetch (same fail-loud semantics as the screener CSV). */
export async function fetchFundsCsv(
  query: FundsCsvQuery = {},
  signal?: AbortSignal,
): Promise<Blob> {
  const qs = fundsParams(query);
  const res = await fetch(`${BASE_URL}/funds.csv${qs ? `?${qs}` : ""}`, {
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
