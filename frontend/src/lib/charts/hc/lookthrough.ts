/**
 * Pure Highcharts option builder: consolidated look-through exposure chart.
 *
 * Horizontal stacked bars (Direct + Via funds), one row per exposure item.
 * Ported 1:1 from the ECharts `buildExposureBarsOption` — same sort/topN gate,
 * same label/total-percent coloring, same null fallback. No finance here, only
 * display arrangement. Chrome (axis grid/tooltip/legend styling) is owned by the
 * global Graphite theme; this builder sets only chart-specific content.
 *
 * Highcharts mapping notes vs ECharts source:
 * - ECharts horizontal bar = Highcharts `chart.type: "bar"` with `inverted: true`.
 * - ECharts category yAxis (row labels) -> Highcharts xAxis (the category axis on
 *   an inverted bar chart). ECharts value xAxis (percent) -> Highcharts yAxis.
 * - ECharts `stack: "exposure"` -> `plotOptions.bar.stacking: "normal"`.
 * - The total-% label rides the outer ("Via funds") series, looked up by point
 *   index, exactly like the source derives the row from `dataIndex`.
 */
import type { Options, Point } from "highcharts";

import type { ExposureItem } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { verticalFill } from "@/lib/charts/hc/gradient";
import { formatNumber } from "@/lib/format";

/**
 * Horizontal stacked bar chart: one row per exposure item, two segments each —
 * Direct (colors.bar / graphite) and Via funds (colors.barMute / grey). Sorted
 * by total_pct descending; top-N rows shown (default 10). A value label at the
 * bar end shows the total formatted as "x.x%". Tooltip shows both segments and
 * the total.
 *
 * @param items     Exposure items for one dimension.
 * @param colors    Design-token color bag (from chartColors()).
 * @param opts.topN Maximum rows to render (default 10).
 */
export function buildHcExposureBarsOption(
  items: ExposureItem[],
  colors: ChartColors,
  opts: { topN?: number } = {},
): Options {
  const topN = opts.topN ?? 10;

  // Sort desc by total, take topN, then reverse so largest renders at the top.
  // (Both ECharts category axis and Highcharts inverted bar render bottom-up,
  // so the reverse keeps the largest row at the top in both libraries.)
  const sorted = [...items]
    .sort((a, b) => b.total_pct - a.total_pct)
    .slice(0, topN)
    .reverse();

  const labels = sorted.map((item) => item.label ?? item.key);

  return {
    chart: { type: "bar", inverted: true },
    legend: {
      enabled: true,
      align: "left",
      verticalAlign: "top",
      symbolRadius: 0,
    },
    xAxis: {
      type: "category",
      categories: labels,
    },
    yAxis: {
      type: "linear",
      title: { text: undefined },
      labels: {
        formatter() {
          return formatNumber(this.value as number, 0) + "%";
        },
      },
    },
    plotOptions: {
      bar: { stacking: "normal" },
      series: { states: { hover: { enabled: false }, inactive: { enabled: false } } },
    },
    tooltip: {
      useHTML: true,
      shared: true,
      formatter(this: Point) {
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        if (!points.length) return "";
        const idx = this.index;
        const row = sorted[idx];
        if (!row) return "";
        const lines = points.map(
          (p) =>
            `<span style="color:${String(p.color)}">■</span> ${p.series.name}: <b>${formatNumber(p.y as number, 2)}%</b>`,
        );
        lines.push(
          `<span style="font-size:11px;color:${colors.textMuted}">Total: <b>${formatNumber(row.total_pct, 2)}%</b></span>`,
        );
        const name = (this.category as string | undefined) ?? "";
        return `<div style="font-size:12px">${name}<br/>${lines.join("<br/>")}</div>`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Direct",
        data: sorted.map((item) => item.direct_pct),
        color: colors.bar,
        dataLabels: { enabled: false },
      },
      {
        type: "bar",
        name: "Via funds",
        data: sorted.map((item) => item.indirect_pct),
        color: colors.barMute,
        dataLabels: {
          enabled: true,
          // Show total (direct + indirect) at the bar end. Highcharts stacks
          // the label on the outer segment; we derive the row from the point
          // index and look up total_pct directly, mirroring the source.
          style: { color: colors.textSecondary, fontWeight: "normal" },
          formatter(this: Point) {
            const idx = this.index;
            const row = sorted[idx];
            if (!row) return "";
            return formatNumber(row.total_pct, 1) + "%";
          },
        },
      },
    ],
  };
}

// ── Issuer Pareto ───────────────────────────────────────────────────────────

/**
 * Well-known issuer aliases. Tested against a lowercased, punctuation-stripped
 * form of the raw N-PORT name; first match wins. Keeps the issuer axis readable
 * ("TSMC" rather than "Taiwan Semiconductor Manufacturing Co Ltd") and folds
 * variants/share-classes onto one canonical issuer.
 */
const ISSUER_ALIASES: Array<[RegExp, string]> = [
  [/^taiwan semiconductor/, "TSMC"],
  [/^(united states|u s|us) treasury/, "U.S. Treasury"],
  // U.S. agencies / GSEs — declared under long legal names but known by nickname.
  [/^(federal national mortgage|fannie mae)/, "Fannie Mae"],
  [/^(federal home loan mortgage|freddie mac)/, "Freddie Mac"],
  [/^(government national mortgage|ginnie mae)/, "Ginnie Mae"],
  [/^federal home loan bank/, "FHLB"],
  [/^federal farm credit/, "Farm Credit"],
  [/^tennessee valley authority/, "TVA"],
  // Capital Group internal "central" funds — kept distinct but two words each.
  [/^capital group central cash/, "CG Cash"],
  [/^capital group central corporate bond/, "CG Corp"],
  [/^capital group central/, "CG Central"],
  [/^meta platforms/, "Meta"],
  [/^alphabet/, "Alphabet"],
  [/^microsoft/, "Microsoft"],
  [/^broadcom/, "Broadcom"],
  [/^nvidia/, "NVIDIA"],
  [/^apple/, "Apple"],
  [/^amazon/, "Amazon"],
  [/^tesla/, "Tesla"],
  [/^berkshire hathaway/, "Berkshire Hathaway"],
  [/^philip morris/, "Philip Morris"],
  [/^(the goldman sachs|goldman sachs)/, "Goldman Sachs"],
  [/^jp ?morgan/, "JPMorgan"],
  [/^johnson and johnson|^johnson & johnson/, "J&J"],
  [/^eli lilly/, "Eli Lilly"],
  [/^exxon mobil/, "ExxonMobil"],
  [/^visa /, "Visa"],
  [/^mastercard/, "Mastercard"],
];

/** Corporate suffixes / share-class noise stripped from non-aliased names. */
const CORP_SUFFIX_RE =
  /\b(inc|incorporated|corp|corporation|co|company|companies|ltd|limited|llc|lp|l p|plc|nv|n v|sa|s a|ag|spa|se|the|holdings?|holding|group|fund|trust|class [a-d]|cl [a-d]|series [a-z0-9]+)\b/g;

/** Keep at most the first `max` words. */
function clampWords(text: string, max = 2): string {
  return text.split(/\s+/).filter(Boolean).slice(0, max).join(" ");
}

/**
 * Sanitize a raw issuer name into a display label and a grouping key. Returns a
 * short, well-known name where an alias matches; otherwise strips corporate
 * suffixes, title-cases, and — as a hard rule — clamps to at most two words so
 * the issuer axis never shows 5–6 word legal names. The `key` lets callers fold
 * issuance-level rows (e.g. two "UNITED STATES TREASURY" lines) onto one issuer.
 */
export function sanitizeIssuerName(raw: string): { display: string; key: string } {
  const lower = raw
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[.,/]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  for (const [re, alias] of ISSUER_ALIASES) {
    if (re.test(lower)) return { display: alias, key: alias.toLowerCase() };
  }
  const stripped = lower.replace(CORP_SUFFIX_RE, " ").replace(/\s+/g, " ").trim();
  const base = clampWords(stripped || lower, 2);
  const display = base.replace(/\b\w/g, (c) => c.toUpperCase());
  return { display, key: base };
}

/**
 * Vertical Pareto chart for issuer concentration: stacked columns (Direct + Via
 * funds, left axis = % of NAV) sorted descending, with a cumulative line on the
 * right axis showing the running share of total issuer exposure. Issuer names
 * are sanitized and aggregated so the same issuer is one column, regardless of
 * how many CUSIPs/issues map to it.
 *
 * @param items     Issuer exposure items.
 * @param colors    Design-token color bag (from chartColors()).
 * @param opts.topN Maximum columns to render (default 15).
 */
export function buildHcIssuerParetoOption(
  items: ExposureItem[],
  colors: ChartColors,
  opts: { topN?: number } = {},
): Options {
  const topN = opts.topN ?? 15;

  // Aggregate by sanitized issuer key — folds issuance-level duplicates.
  const agg = new Map<
    string,
    { display: string; direct: number; indirect: number; total: number }
  >();
  for (const item of items) {
    const { display, key } = sanitizeIssuerName(item.label ?? item.key);
    const cur = agg.get(key) ?? { display, direct: 0, indirect: 0, total: 0 };
    cur.direct += item.direct_pct;
    cur.indirect += item.indirect_pct;
    cur.total += item.total_pct;
    agg.set(key, cur);
  }

  const all = [...agg.values()].sort((a, b) => b.total - a.total);
  const grandTotal = all.reduce((sum, row) => sum + row.total, 0) || 1;
  const shown = all.slice(0, topN);

  let running = 0;
  const cumulative = shown.map((row) => {
    running += row.total;
    return (running / grandTotal) * 100;
  });

  return {
    chart: { type: "column" },
    legend: {
      enabled: true,
      align: "left",
      verticalAlign: "top",
      symbolRadius: 0,
    },
    xAxis: {
      type: "category",
      categories: shown.map((row) => row.display),
      labels: { rotation: -40, style: { fontSize: "11px" } },
    },
    yAxis: [
      {
        title: { text: "% of NAV" },
        labels: {
          formatter() {
            return formatNumber(this.value as number, 0) + "%";
          },
        },
      },
      {
        title: { text: "Cumulative" },
        opposite: true,
        min: 0,
        max: 100,
        labels: {
          formatter() {
            return formatNumber(this.value as number, 0) + "%";
          },
        },
      },
    ],
    tooltip: {
      useHTML: true,
      shared: true,
      formatter(this: Point) {
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        if (!points.length) return "";
        const name =
          (points[0].key as string | undefined) ??
          (this.category as string | undefined) ??
          "";
        const lines = points.map((p) => {
          const isLine = p.series.type === "line";
          return `<span style="color:${String(p.color)}">${
            isLine ? "—" : "■"
          }</span> ${p.series.name}: <b>${formatNumber(p.y as number, 2)}%</b>`;
        });
        return `<div style="font-size:12px">${name}<br/>${lines.join("<br/>")}</div>`;
      },
    },
    plotOptions: {
      column: { stacking: "normal", borderWidth: 0 },
      series: { states: { inactive: { enabled: false } } },
    },
    series: [
      {
        type: "column",
        name: "Direct",
        data: shown.map((row) => row.direct),
        color: verticalFill(colors.categories[0]),
        yAxis: 0,
      },
      {
        type: "column",
        name: "Via funds",
        data: shown.map((row) => row.indirect),
        color: verticalFill(colors.categories[4]),
        yAxis: 0,
      },
      {
        type: "line",
        name: "Cumulative",
        data: cumulative,
        color: colors.accent,
        yAxis: 1,
        lineWidth: 2,
        marker: {
          enabled: true,
          radius: 3,
          symbol: "circle",
          fillColor: colors.accent,
          lineColor: colors.surface,
          lineWidth: 1,
        },
        zIndex: 5,
      },
    ],
  };
}

// ── Asset-class pie ─────────────────────────────────────────────────────────

/** Canonical 4-bucket order (matches the system asset-class taxonomy). */
const ASSET_CLASS_ORDER = ["Equities", "Fixed Income", "Alternatives", "Cash"] as const;

/**
 * Raw N-PORT asset-class codes → the four system buckets. Mirrors the backend
 * taxonomy (`lookthrough._fallback_taxonomy_from_nport` + `_normalize_asset_class`):
 * equities, fixed income, alternatives, cash. Unknown codes fall to Alternatives.
 */
const ASSET_CLASS_BUCKET: Record<string, (typeof ASSET_CLASS_ORDER)[number]> = {
  EC: "Equities",
  EP: "Equities",
  EQ: "Equities",
  DE: "Equities",
  EQUITY: "Equities",
  EQUITIES: "Equities",
  DBT: "Fixed Income",
  ABS: "Fixed Income",
  "ABS-MBS": "Fixed Income",
  "ABS-O": "Fixed Income",
  "ABS-CBDO": "Fixed Income",
  "ABS-APCP": "Fixed Income",
  CMBS: "Fixed Income",
  MBS: "Fixed Income",
  UST: "Fixed Income",
  CORP: "Fixed Income",
  MUNI: "Fixed Income",
  SN: "Fixed Income",
  LON: "Fixed Income",
  FIXED_INCOME: "Fixed Income",
  "FIXED INCOME": "Fixed Income",
  STIV: "Cash",
  CASH: "Cash",
  MM: "Cash",
  MMF: "Cash",
  RA: "Cash",
  RE: "Alternatives",
  COMM: "Alternatives",
  DCO: "Alternatives",
  DCR: "Alternatives",
  DFE: "Alternatives",
  DIR: "Alternatives",
  DSE: "Alternatives",
  ALTERNATIVES: "Alternatives",
};

/** Map a raw asset-class code/label to one of the four system buckets. */
export function bucketForAssetClass(code: string): (typeof ASSET_CLASS_ORDER)[number] {
  return ASSET_CLASS_BUCKET[code.trim().toUpperCase()] ?? "Alternatives";
}

interface AssetClassSlice {
  name: string;
  y: number;
  color: string;
  direct: number;
  indirect: number;
}

/**
 * Donut pie of asset-class exposure, normalized into the four system buckets
 * (Equities / Fixed Income / Alternatives / Cash) and colored from the chart
 * palette. Pairs with the custom fan-in entrance animation registered on the
 * pie series. Tooltip breaks each slice into Direct vs Via funds.
 */
export function buildHcAssetClassPieOption(
  items: ExposureItem[],
  colors: ChartColors,
): Options {
  const colorByBucket: Record<string, string> = {
    Equities: colors.categories[0],
    "Fixed Income": colors.categories[1],
    Alternatives: colors.categories[2],
    Cash: colors.categories[3],
  };

  const agg = new Map<string, { direct: number; indirect: number; total: number }>();
  for (const item of items) {
    const bucket = bucketForAssetClass(item.label ?? item.key);
    const cur = agg.get(bucket) ?? { direct: 0, indirect: 0, total: 0 };
    cur.direct += item.direct_pct;
    cur.indirect += item.indirect_pct;
    cur.total += item.total_pct;
    agg.set(bucket, cur);
  }

  const data: AssetClassSlice[] = ASSET_CLASS_ORDER.filter((b) => agg.has(b)).map(
    (bucket) => {
      const row = agg.get(bucket)!;
      return {
        name: bucket,
        y: row.total,
        color: colorByBucket[bucket],
        direct: row.direct,
        indirect: row.indirect,
      };
    },
  );

  return {
    chart: { type: "pie" },
    legend: {
      enabled: true,
      align: "center",
      verticalAlign: "bottom",
      symbolRadius: 0,
    },
    tooltip: {
      useHTML: true,
      formatter(this: Point) {
        const ctx = this as unknown as { point?: AssetClassSlice & { percentage?: number }; percentage?: number };
        const slice = (ctx.point ?? (this as unknown as AssetClassSlice)) as AssetClassSlice;
        const percentage = ctx.percentage ?? ctx.point?.percentage ?? 0;
        return (
          `<div style="font-size:12px"><b>${slice.name}</b><br/>` +
          `${formatNumber(percentage, 1)}% of exposure · ${formatNumber(slice.y, 2)}% of NAV<br/>` +
          `<span style="color:${colors.textMuted}">Direct ${formatNumber(
            slice.direct,
            2,
          )}% · Via funds ${formatNumber(slice.indirect, 2)}%</span></div>`
        );
      },
    },
    plotOptions: {
      pie: {
        innerSize: "55%",
        borderWidth: 2,
        borderColor: colors.surface,
        animation: { duration: 1200 },
        dataLabels: {
          enabled: true,
          distance: 16,
          connectorWidth: 1,
          style: {
            fontSize: "12px",
            fontWeight: "normal",
            color: colors.text,
            textOutline: "none",
          },
          formatter(this: Point) {
            const ctx = this as unknown as {
              point?: { name?: string; percentage?: number };
              name?: string;
              percentage?: number;
            };
            const name = ctx.point?.name ?? ctx.name ?? "";
            const percentage = ctx.percentage ?? ctx.point?.percentage ?? 0;
            return `${name}<br/><b>${formatNumber(percentage, 1)}%</b>`;
          },
        },
        states: { hover: { brightness: 0.1, halo: { size: 8, opacity: 0.2 } } },
      },
    },
    series: [
      {
        type: "pie",
        name: "Exposure",
        data,
        animation: { duration: 1200 },
      },
    ],
  };
}
