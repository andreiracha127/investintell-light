/**
 * Pure option builders for the Macro / Market Regime page (Highcharts Core).
 *
 * Currently exposes `buildHcMacroPerformanceOption` (portfolio vs benchmark with
 * risk-off plot bands). The regime rotation graph lives in `macro-rrg.ts`; the
 * earlier `buildHcRegimeStripOption` / `buildHcMacroRotationOption` builders were
 * superseded and removed.
 */
import type { Options } from "highcharts";

import type { MacroRegime } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { compactDatetimeXAxis, dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import { formatDate, formatNumber } from "@/lib/format";

// ── Color math ─────────────────────────────────────────────────────────────

/**
 * Encode an alpha into a `#RRGGBB` token as an `rgba(r, g, b, a)` string.
 * Pass-through any input that is not a 6-digit hex (e.g. already-rgba or named
 * colors) so the helper never corrupts an unexpected token.
 */
function withAlpha(hex: string, a: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const int = parseInt(m[1], 16);
  const r = (int >> 16) & 0xff;
  const g = (int >> 8) & 0xff;
  const b = int & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** Encode a `#RRGGBB` token at the given alpha (reuses the local helper). */
function tint(hex: string, a: number): string {
  return withAlpha(hex, a);
}

type RegimeHistoryPoint = MacroRegime["history"][number];
type DatePoint = [string, number];

function normalizeSeries(points: DatePoint[]): Array<[number, number]> {
  const first = points.find(([, value]) => Number.isFinite(value) && value > 0);
  if (!first) return [];
  const base = first[1];
  return points
    .filter(([, value]) => Number.isFinite(value))
    .map(([date, value]) => [dateToUtcMs(date), (value / base) * 100]);
}

/**
 * Clip both series to their first COMMON date so "Indexed to 100" curves are
 * rebased on the same day. Two series rebased at different inceptions both
 * start at 100 on different dates and stop being comparable. No-op when either
 * series is empty (the panel gates rendering on both being present anyway).
 */
function clipToCommonStart(
  a: DatePoint[],
  b: DatePoint[],
): [DatePoint[], DatePoint[]] {
  const firstValid = (points: DatePoint[]): number | null => {
    const hit = points.find(([, value]) => Number.isFinite(value) && value > 0);
    return hit ? dateToUtcMs(hit[0]) : null;
  };
  const firstA = firstValid(a);
  const firstB = firstValid(b);
  if (firstA === null || firstB === null) return [a, b];
  const start = Math.max(firstA, firstB);
  return [
    a.filter(([date]) => dateToUtcMs(date) >= start),
    b.filter(([date]) => dateToUtcMs(date) >= start),
  ];
}

/**
 * Running drawdown from each prior peak, expressed as a non-positive percent
 * (0% at every new high). Mirrors the prototype's `drawdown` helper.
 */
function drawdownSeries(points: DatePoint[]): Array<[number, number]> {
  const clean = points.filter(([, value]) => Number.isFinite(value));
  let peak = -Infinity;
  return clean.map(([date, value]) => {
    peak = Math.max(peak, value);
    return [dateToUtcMs(date), peak > 0 ? (value / peak - 1) * 100 : 0];
  });
}

/**
 * Risk-off windows drawn as FRED-style recession shading: only `risk_off`
 * periods are shaded (risk_on windows are left clear). Each band carries a
 * 1px border so the shaded run reads as a discrete window, and no per-band
 * label text (the inline legend names the band instead).
 */
function deriveRegimePlotBands(
  history: RegimeHistoryPoint[],
  minX: number,
  maxX: number,
  colors: ChartColors,
) {
  const sorted = [...history]
    .filter((point) => Number.isFinite(dateToUtcMs(point.date)))
    .sort((a, b) => a.date.localeCompare(b.date));
  const bands = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const start = dateToUtcMs(sorted[i].date);
    if (start > maxX) break;
    const state = sorted[i].state;
    let j = i + 1;
    while (j < sorted.length && sorted[j].state === state) j += 1;
    // Only shade risk_off windows; advance past contiguous same-state runs.
    if (state !== "risk_off") {
      i = j - 1;
      continue;
    }
    const end = j < sorted.length ? dateToUtcMs(sorted[j].date) : maxX;
    // Skip windows entirely left of the visible range; clamp ones that straddle
    // the left edge so a risk-off run starting before minX still shades in-view.
    if (end <= minX) {
      i = j - 1;
      continue;
    }
    bands.push({
      from: Math.max(start, minX),
      to: Math.min(end, maxX),
      color: withAlpha(colors.loss, 0.16),
      borderColor: withAlpha(colors.loss, 0.4),
      borderWidth: 1,
    });
    i = j - 1;
  }
  return bands;
}

export type MacroPerformanceView = "indexed" | "drawdown";

export function buildHcMacroPerformanceOption({
  portfolio,
  asset,
  regimes,
  colors,
  portfolioLabel,
  assetLabel,
  view = "indexed",
}: {
  portfolio: DatePoint[];
  asset: DatePoint[];
  regimes: RegimeHistoryPoint[];
  colors: ChartColors;
  portfolioLabel: string;
  assetLabel: string;
  /** "indexed" rebases both series to 100; "drawdown" shows decline from peak. */
  view?: MacroPerformanceView;
}): Options | null {
  const isDrawdown = view === "drawdown";
  const project = isDrawdown ? drawdownSeries : normalizeSeries;
  // Same start date for both curves — rebasing (and peak-tracking) must begin
  // on the same day for the two series to be comparable.
  const [portfolioAligned, assetAligned] = clipToCommonStart(portfolio, asset);
  const portfolioData = project(portfolioAligned);
  const assetData = project(assetAligned);
  const allTimes = [...portfolioData, ...assetData].map(([time]) => time);
  if (allTimes.length === 0) return null;
  const minX = Math.min(...allTimes);
  const maxX = Math.max(...allTimes);
  const refLine = isDrawdown ? 0 : 100;

  return {
    chart: { type: "line", zooming: { type: "x" } },
    // The page renders its own inline HTML legend; suppress the Highcharts one.
    legend: { enabled: false },
    xAxis: compactDatetimeXAxis({
      min: minX,
      max: maxX,
      crosshair: { color: colors.grid },
      tickPixelInterval: 96,
      plotBands: deriveRegimePlotBands(regimes, minX, maxX, colors),
    }),
    yAxis: {
      title: { text: isDrawdown ? "Drawdown" : "Indexed to 100" },
      labels: {
        formatter() {
          return isDrawdown
            ? `${formatNumber(this.value as number, 0)}%`
            : formatNumber(this.value as number, 0);
        },
      },
      plotLines: [
        { value: refLine, width: 1, color: colors.textMuted, dashStyle: "Dash", zIndex: 2 },
      ],
    },
    tooltip: {
      shared: true,
      formatter() {
        const rows = (this.points ?? [])
          .map((point) => {
            const value = point.y as number;
            const formatted = isDrawdown
              ? `${formatNumber(value, 1)}%`
              : formatNumber(value, 2);
            return `<span style="color:${point.series.color}">●</span> ${point.series.name}: <b>${formatted}</b>`;
          })
          .join("<br/>");
        return `${formatDate(new Date(this.x as number).toISOString().slice(0, 10))}<br/>${rows}`;
      },
    },
    series: [
      {
        type: isDrawdown ? "area" : "line",
        name: portfolioLabel,
        data: portfolioData,
        color: colors.accent,
        lineWidth: 2.2,
        marker: { enabled: false },
        fillColor: isDrawdown ? tint(colors.accent, 0.12) : undefined,
        zIndex: 3,
      },
      {
        type: "line",
        name: assetLabel,
        data: assetData,
        color: colors.barMute,
        lineWidth: 1.6,
        marker: { enabled: false },
        dashStyle: isDrawdown ? "ShortDash" : "Solid",
        zIndex: 2,
      },
    ],
  };
}
