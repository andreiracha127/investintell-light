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

/**
 * Format a screener metric value by its catalog `data_type`.
 *
 * - "percent": API decimal fractions (0.05 = 5%) via formatPercent.
 * - "currency": compact USD ("$3.4B") — screener currency metrics are
 *   market-cap-scale, where full Intl currency output is unreadable.
 * - "int": compact count.
 * - anything else (float / unknown): plain 2dp number.
 */
export function formatMetricValue(value: number, dataType: string): string {
  switch (dataType) {
    case "percent":
      return formatPercent(value, 2);
    case "currency":
      return value < 0 ? `-$${formatCompact(-value)}` : `$${formatCompact(value)}`;
    case "int":
      return formatCompact(value);
    default:
      return formatNumber(value, 2);
  }
}

/** Format an ISO date string (YYYY-MM-DD) as "Jun 10, 2026" (UTC-safe). */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const day = isoDate.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return "—";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}
