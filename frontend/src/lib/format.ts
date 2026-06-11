/**
 * Centralized formatters — the ONLY place numbers become display strings.
 *
 * Components and chart option builders import from here; they never call
 * `toFixed` / `Intl` directly. All percent inputs are decimal fractions
 * (0.05 = 5%), matching the backend contract.
 */

/** Format a decimal fraction as a percent string: 0.0512 -> "5.12%". */
export function formatPercent(
  fraction: number,
  dp = 2,
  { signed = false }: { signed?: boolean } = {},
): string {
  const pct = (fraction * 100).toFixed(dp);
  const sign = signed && fraction > 0 ? "+" : "";
  return `${sign}${pct}%`;
}

/** Format a currency amount: 1234.5 -> "$1,234.50". */
export function formatCurrency(
  value: number,
  { signed = false }: { signed?: boolean } = {},
): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(value);
}

/** Compact notation for large counts (volume): 1234567 -> "1.2M". */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Plain fixed-precision number: 1.2345 -> "1.23". */
export function formatNumber(value: number, dp = 2): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  }).format(value);
}

/** Format an ISO date string (YYYY-MM-DD) as "Jun 10, 2026" (UTC-safe). */
export function formatDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}
