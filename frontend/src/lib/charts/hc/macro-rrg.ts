/**
 * Pure option builder: Macro Relative Rotation Graph (RRG) — Highcharts Core.
 *
 * Faithful translation of the `Macro.dc.html` prototype's `_buildRotation`,
 * but driven by the REAL `MacroRegime.history` signal series instead of mock
 * data. Each of the three regime signals — Credit appetite, Trend and Financial
 * conditions — and their Composite trace a short "tail" (spline) through a
 * four-quadrant plane:
 *
 *   X axis (RS-Ratio)    = relative strength / risk appetite     (right = more)
 *   Y axis (RS-Momentum) = rate of change of that strength       (up = improving)
 *
 * Both axes are centred on 100 (the RRG convention). The four quadrants read,
 * matching the prototype:
 *
 *   top-left  RECOVERY     (weak strength, improving momentum)
 *   top-right EXPANSION    (strong strength, improving momentum)
 *   bot-left  CONTRACTION  (weak strength, weakening momentum)
 *   bot-right SLOWDOWN     (strong strength, weakening momentum)
 *
 * Per-signal strength proxies, all "higher = more risk appetite":
 *   credit     = signal.distance_pct  (ratio above its 5y risk-off trigger)
 *   trend      = ratio − trailing mean (momentum of the credit-appetite ratio)
 *   conditions = −nfci                 (looser financial conditions)
 * The composite is the mean of the three standardised signals.
 *
 * Quadrant background washes are drawn on a `render` event (gain/loss gradient
 * fills clipped to each quadrant of the plot area), exactly like the prototype's
 * `_drawQuadBg`. Reference lines sit at x=100 and y=100. The most recent point
 * of every tail gets a larger "today" marker.
 *
 * Returns `null` for empty history (caller hides the panel).
 */
import type Highcharts from "highcharts";
import type { Options, Point } from "highcharts";

import type { MacroRegime } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatDate } from "@/lib/format";

type RegimeHistoryPoint = MacroRegime["history"][number];

// ── Axis envelope (mirrors the prototype's quadrant convention) ──────────────
const AXIS_MIN = 96;
const AXIS_MAX = 104;
const CLAMP_LO = 96.2;
const CLAMP_HI = 103.8;
const TARGET_TAIL_RADIUS = 3.15;
const MAX_TAIL_SCALE = 8;

/** Number of tail vertices drawn per signal. */
const TAIL = 11;

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

/** Standardise an array to zero mean / unit variance (z-score). */
function zscore(arr: number[]): number[] {
  if (arr.length === 0) return [];
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const variance = arr.reduce((a, b) => a + (b - mean) * (b - mean), 0) / arr.length;
  const sd = Math.sqrt(variance) || 1e-6;
  return arr.map((x) => (x - mean) / sd);
}

/** Trailing simple moving average (window `w`), expanding for the warm-up. */
function smooth(arr: number[], w: number): number[] {
  const out: number[] = [];
  let run = 0;
  for (let i = 0; i < arr.length; i += 1) {
    run += arr[i];
    if (i >= w) run -= arr[i - w];
    out.push(run / Math.min(i + 1, w));
  }
  return out;
}

/** Map a `#RRGGBB` token to an `r,g,b` triplet string for rgba() gradients. */
function rgbTriplet(hex: string): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return "127,127,127";
  const int = parseInt(m[1], 16);
  return `${(int >> 16) & 0xff}, ${(int >> 8) & 0xff}, ${int & 0xff}`;
}

interface TailVertex {
  x: number;
  y: number;
  date: string;
}

/**
 * Build per-signal tail vertices from a standardised, smoothed strength series.
 *
 * Strength → X (centred on 100); momentum (Δ strength over `look` steps) → Y.
 * Samples the last `TAIL` vertices spaced `step` apart so the tail reads as a
 * smooth sweep over the selected window. Mirrors the prototype's `mkTail`. The
 * real date for each vertex is spliced on from the parallel `dates` array.
 */
function buildTail(
  strength: number[],
  dates: string[],
  step: number,
  look: number,
): TailVertex[] {
  const last = strength.length - 1;
  const out: TailVertex[] = [];
  for (let k = 0; k < TAIL; k += 1) {
    const idx = last - (TAIL - 1 - k) * step;
    if (idx < look) continue;
    const x = clamp(100 + strength[idx], CLAMP_LO, CLAMP_HI);
    const y = clamp(100 + (strength[idx] - strength[idx - look]) * 1.6, CLAMP_LO, CLAMP_HI);
    out.push({ x, y, date: dates[idx] ?? dates[last] ?? "" });
  }
  return out;
}

function fitTailsToEnvelope(tails: TailVertex[][]): TailVertex[][] {
  const maxDistance = Math.max(
    0,
    ...tails.flatMap((tail) =>
      tail.flatMap((point) => [Math.abs(point.x - 100), Math.abs(point.y - 100)]),
    ),
  );
  const scale =
    maxDistance > 0 ? Math.min(MAX_TAIL_SCALE, TARGET_TAIL_RADIUS / maxDistance) : 1;
  if (scale <= 1.01) return tails;

  return tails.map((tail) =>
    tail.map((point) => ({
      ...point,
      x: clamp(100 + (point.x - 100) * scale, CLAMP_LO, CLAMP_HI),
      y: clamp(100 + (point.y - 100) * scale, CLAMP_LO, CLAMP_HI),
    })),
  );
}

/** Quadrant labels (corner anchors), matching the prototype. */
interface QuadLabel {
  x: number;
  y: number;
  text: string;
  colorKey: "improving" | "leading" | "lagging" | "weakening";
}

const QUAD_LABELS: QuadLabel[] = [
  { x: 96.15, y: 103.85, text: "RECOVERY", colorKey: "improving" },
  { x: 103.85, y: 103.85, text: "EXPANSION", colorKey: "leading" },
  { x: 96.15, y: 96.15, text: "CONTRACTION", colorKey: "lagging" },
  { x: 103.85, y: 96.15, text: "SLOWDOWN", colorKey: "weakening" },
];

export interface MacroRrgColors {
  composite: string;
  credit: string;
  trend: string;
  conditions: string;
  /** Quadrant wash rgb triplets. */
  improving: string;
  leading: string;
  lagging: string;
  weakening: string;
}

/**
 * Derive the rotation palette from the design tokens. The composite uses the
 * design accent; the three signals fan out blue / green / amber; the four
 * quadrant washes are improving=blue, leading=green, lagging=red, weakening=amber
 * — matching the `Macro.dc.html` prototype. Blue and amber come from the token
 * layer (`--color-chart-blue/amber`, themed) via `chartColors()`; green and red
 * are `colors.gain` / `colors.loss`.
 */
function rrgColors(colors: ChartColors): MacroRrgColors {
  return {
    composite: colors.accent,
    credit: colors.blue,
    trend: colors.gain,
    conditions: colors.amber,
    improving: rgbTriplet(colors.blue),
    leading: rgbTriplet(colors.gain),
    lagging: rgbTriplet(colors.loss),
    weakening: rgbTriplet(colors.amber),
  };
}

interface QuadBgChart extends Highcharts.Chart {
  __quadBg?: Highcharts.SVGElement | null;
}

/**
 * Draw the four quadrant gradient washes, clipped to the plot area, on every
 * chart `render`. Each wash fades from the corner inward, exactly like the
 * prototype's `_drawQuadBg`.
 */
function drawQuadrantBackground(chart: QuadBgChart, rc: MacroRrgColors, alpha: number): void {
  if (chart.__quadBg) {
    try {
      chart.__quadBg.destroy();
    } catch {
      /* already gone */
    }
    chart.__quadBg = null;
  }
  const renderer = chart.renderer;
  const xAxis = chart.xAxis[0];
  const yAxis = chart.yAxis[0];
  if (!xAxis || !yAxis) return;

  const pl = chart.plotLeft;
  const pt = chart.plotTop;
  const pw = chart.plotWidth;
  const ph = chart.plotHeight;
  const cx = Math.round(xAxis.toPixels(100, false));
  const cy = Math.round(yAxis.toPixels(100, false));

  const group = renderer.g("ix-quadbg").attr({ zIndex: 0 }).add();

  const quad = (
    x: number,
    y: number,
    w: number,
    h: number,
    grad: { x1: number; y1: number; x2: number; y2: number },
    rgb: string,
  ): void => {
    if (w <= 0 || h <= 0) return;
    renderer
      .rect(x, y, w, h)
      .attr({
        fill: {
          linearGradient: grad,
          stops: [
            [0, `rgba(${rgb},${alpha})`],
            [1, `rgba(${rgb},0)`],
          ],
        },
      })
      .add(group);
  };

  // top-left RECOVERY (improving), top-right EXPANSION (leading),
  // bottom-left CONTRACTION (lagging), bottom-right SLOWDOWN (weakening)
  quad(pl, pt, cx - pl, cy - pt, { x1: 0, y1: 0, x2: 1, y2: 1 }, rc.improving);
  quad(cx, pt, pl + pw - cx, cy - pt, { x1: 1, y1: 0, x2: 0, y2: 1 }, rc.leading);
  quad(pl, cy, cx - pl, pt + ph - cy, { x1: 0, y1: 1, x2: 1, y2: 0 }, rc.lagging);
  quad(cx, cy, pl + pw - cx, pt + ph - cy, { x1: 1, y1: 1, x2: 0, y2: 0 }, rc.weakening);

  chart.__quadBg = group;
}

/**
 * Build the Macro RRG option from regime history.
 *
 * @param history  The `MacroRegime.history` series (chronological).
 * @param colors   Design-token color bag.
 * @param options  `step`/`look` control tail spacing & momentum look-back so the
 *                 caller can widen the sweep for longer periods. `darkTheme`
 *                 deepens the quadrant washes.
 * @returns Highcharts `Options`, or `null` when there is no history.
 */
export function buildHcMacroRrgOption(
  history: RegimeHistoryPoint[],
  colors: ChartColors,
  options: { step?: number; look?: number; darkTheme?: boolean } = {},
): Options | null {
  if (!history || history.length === 0) return null;

  const rc = rrgColors(colors);
  const step = Math.max(1, options.step ?? 8);
  const look = Math.max(6, options.look ?? step);
  const window = Math.max(16, step * 4);
  const alpha = options.darkTheme ? 0.34 : 0.3;

  // Raw strength proxies (higher = more risk appetite).
  const ratio = history.map((p) => p.signal.ratio ?? 0);
  const trailMean = smooth(ratio, window);
  const rawCredit = history.map((p) => p.signal.distance_pct ?? 0);
  const rawTrend = ratio.map((r, i) => (trailMean[i] ? (r / trailMean[i] - 1) * 100 : 0));
  const rawConditions = history.map((p) => -(p.signal.nfci ?? 0));

  // Standardise then smooth; a second pass below fits quiet periods into the
  // quadrant envelope so long ranges do not collapse into an unreadable centre.
  const SCALE = 1.15;
  const zc = smooth(zscore(rawCredit), window).map((z) => z * SCALE);
  const zt = smooth(zscore(rawTrend), window).map((z) => z * SCALE);
  const zn = smooth(zscore(rawConditions), window).map((z) => z * SCALE);
  const zk = zc.map((_, i) => (zc[i] + zt[i] + zn[i]) / 3);

  const dates = history.map((p) => p.date);

  /** Build a tail with real dates spliced back onto each vertex. */
  const tailFor = (strength: number[]): TailVertex[] => buildTail(strength, dates, step, look);

  const defs: Array<{
    name: string;
    strength: number[];
    color: string;
    lineWidth: number;
    dashStyle: Highcharts.DashStyleValue;
  }> = [
    { name: "Composite", strength: zk, color: rc.composite, lineWidth: 3.2, dashStyle: "Solid" },
    { name: "Credit", strength: zc, color: rc.credit, lineWidth: 2, dashStyle: "Dot" },
    { name: "Trend", strength: zt, color: rc.trend, lineWidth: 2, dashStyle: "Dot" },
    { name: "Conditions", strength: zn, color: rc.conditions, lineWidth: 2, dashStyle: "Dot" },
  ];

  const fittedTails = fitTailsToEnvelope(defs.map((def) => tailFor(def.strength)));

  const tailSeries: Highcharts.SeriesOptionsType[] = defs.map((def, defIndex) => {
    const verts = fittedTails[defIndex] ?? [];
    const data = verts.map((v, i) => ({
      x: v.x,
      y: v.y,
      custom: { date: v.date, signal: def.name },
      marker:
        i === verts.length - 1
          ? {
              symbol: "circle",
              radius: def.name === "Composite" ? 7 : 6,
              fillColor: def.color,
              lineColor: colors.surface,
              lineWidth: 1.75,
            }
          : {
              symbol: "circle",
              radius: def.name === "Composite" ? 3.4 : 3,
              fillColor: def.color,
              lineWidth: 0,
            },
    }));
    return {
      type: "spline",
      name: def.name,
      data,
      color: def.color,
      lineWidth: def.lineWidth,
      dashStyle: def.dashStyle,
      zIndex: def.name === "Composite" ? 5 : 4,
      marker: { enabled: true, symbol: "circle" },
      states: { inactive: { opacity: 1 } },
    };
  });

  const quadLabelSeries: Highcharts.SeriesOptionsType = {
    type: "scatter",
    name: "Quadrants",
    enableMouseTracking: false,
    showInLegend: false,
    zIndex: 1,
    marker: { enabled: false },
    data: QUAD_LABELS.map((q) => ({
      x: q.x,
      y: q.y,
      dataLabels: {
        enabled: true,
        allowOverlap: true,
        format: q.text,
        align: q.x < 100 ? "left" : "right",
        verticalAlign: q.y > 100 ? "top" : "bottom",
        x: q.x < 100 ? 2 : -2,
        y: q.y > 100 ? 2 : -2,
        style: {
          color:
            q.colorKey === "improving"
              ? rc.credit
              : q.colorKey === "leading"
                ? colors.gain
                : q.colorKey === "lagging"
                  ? colors.loss
                  : rc.conditions,
          fontSize: "10px",
          fontWeight: "700",
          textOutline: "none",
        },
      },
    })),
  };

  const axisCommon = {
    min: AXIS_MIN,
    max: AXIS_MAX,
    tickInterval: 2,
    gridLineWidth: 1,
    gridLineColor: colors.grid,
    title: { text: undefined },
    labels: { enabled: false },
  } as const;

  return {
    chart: {
      type: "spline",
      spacing: [8, 10, 6, 10],
      events: {
        render(this: Highcharts.Chart) {
          drawQuadrantBackground(this as QuadBgChart, rc, alpha);
        },
      },
    },
    legend: { enabled: false },
    title: { text: undefined },
    xAxis: {
      ...axisCommon,
      lineWidth: 0,
      tickLength: 0,
      plotLines: [{ value: 100, width: 1.4, color: colors.textSecondary, zIndex: 3 }],
    },
    yAxis: {
      ...axisCommon,
      plotLines: [{ value: 100, width: 1.4, color: colors.textSecondary, zIndex: 3 }],
    },
    tooltip: {
      useHTML: true,
      formatter(this: Point) {
        const custom = (
          this as unknown as { point?: { custom?: { date?: string; signal?: string } } }
        ).point?.custom ??
          (this as unknown as { custom?: { date?: string; signal?: string } }).custom;
        const signal = custom?.signal ?? this.series.name;
        const date = custom?.date;
        return (
          `<b style="color:${this.series.color}">${signal}</b><br/>` +
          `<span style="color:${colors.textMuted}">${date ? formatDate(date) : ""}</span>`
        );
      },
    },
    plotOptions: {
      spline: {
        marker: { enabled: true, symbol: "circle" },
        dataLabels: { enabled: false },
        states: { hover: { lineWidthPlus: 1, halo: { size: 5 } } },
      },
      scatter: { enableMouseTracking: false, marker: { enabled: false } },
      series: { animation: { duration: 300 } },
    },
    series: [quadLabelSeries, ...tailSeries],
  };
}
