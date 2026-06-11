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

export type StockAnalysis =
  AnalysisOperation["responses"]["200"]["content"]["application/json"];
export type AnalysisQuery = NonNullable<AnalysisOperation["parameters"]["query"]>;
export type RangePreset = NonNullable<AnalysisQuery["range"]>;
export type PriceSeries =
  PricesOperation["responses"]["200"]["content"]["application/json"];
export type TickerNews =
  NewsOperation["responses"]["200"]["content"]["application/json"];
export type NewsArticle = TickerNews["items"][number];

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

/** Extract the backend `detail` from an error body, else a status fallback. */
function extractDetail(body: unknown, fallback: string): string {
  if (body !== null && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail !== undefined) return JSON.stringify(detail);
  }
  return fallback;
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(15_000);
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal;

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, { signal: combinedSignal });
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
  return (await res.json()) as T;
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
