/**
 * Pure option builder: allocation donut (Cockpit style) for Highcharts Core.
 *
 * When slices include `assetClass`, renders a two-level donut: inner ring by
 * asset class, outer ring by holding. Without `assetClass`, it preserves the
 * legacy one-ring donut.
 * Global chrome (tooltip background, legend styling, grid, animation) is owned by
 * the Graphite theme applied via `Highcharts.setOptions(...)`.
 *
 * Config:
 *  - `innerSize` — donut hole (default "62%", matching the mockup).
 *  - `dataLabels` — leader labels "name x%" inside the chart (Builder donuts,
 *    which have no external legend). Default off (Portfolio renders an HTML legend).
 *  - `valueFormatter` — when set, the tooltip adds a formatted value line above
 *    the "% of portfolio" line (e.g. the currency value for the Portfolio donut).
 *
 * Input types live in the neutral chart types module for shared consumers.
 */
import type { ColorString, Options, Point, SeriesPieOptions } from "highcharts";

import type { AllocationSlice } from "@/lib/charts/types";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

export interface AllocationConfig {
  innerSize?: string;
  dataLabels?: boolean;
  valueFormatter?: (value: number) => string;
}

function assetClassLabel(assetClass: string | null | undefined): string {
  if (!assetClass) return "Other";
  const normalized = assetClass.trim().toLowerCase();
  const labels: Record<string, string> = {
    alternatives: "Alternatives",
    cash: "Cash",
    equity: "Equity",
    fixed_income: "Fixed Income",
    multi_asset: "Multi-Asset",
  };
  return labels[normalized] ?? assetClass.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function pointColor(slice: AllocationSlice, index: number, colors: ChartColors): string {
  return slice.name === "Cash" || slice.assetClass === "cash"
    ? colors.barMute
    : colors.categories[index % colors.categories.length];
}

export function buildHcAllocationOption(
  slices: AllocationSlice[],
  colors: ChartColors,
  config: AllocationConfig = {},
): Options {
  const innerSize = config.innerSize ?? "62%";
  const valueFormatter = config.valueFormatter;
  const hasAssetClasses = slices.some((slice) => slice.assetClass);
  const holdingData = slices.map((slice, i) => ({
    name: slice.name,
    y: slice.value,
    color: pointColor(slice, i, colors),
    custom: {
      assetClass: assetClassLabel(slice.assetClass),
      displayName: slice.displayName,
    },
  }));

  const classTotals = new Map<string, { color: string; value: number }>();
  slices.forEach((slice, i) => {
    const label = assetClassLabel(slice.assetClass);
    const current = classTotals.get(label);
    if (current) {
      current.value += slice.value;
    } else {
      classTotals.set(label, { color: pointColor(slice, i, colors), value: slice.value });
    }
  });

  const innerData = Array.from(classTotals, ([name, item]) => ({
    name,
    y: item.value,
    color: item.color,
  }));

  const singleSeries: SeriesPieOptions = {
    type: "pie",
    name: "Allocation",
    innerSize,
    borderWidth: 1,
    borderColor: colors.surface,
    dataLabels: config.dataLabels
      ? {
          enabled: true,
          distance: 12,
          connectorWidth: 1,
          connectorColor: colors.grid,
          style: { fontWeight: "400", textOutline: "none", color: colors.text },
          formatter(this: Point) {
            return `${String(this.key ?? this.name ?? "")} ${Math.round(this.percentage ?? 0)}%`;
          },
        }
      : { enabled: false },
    states: { hover: { halo: { size: 4 }, brightness: 0.08 } },
    data: holdingData,
  };

  const nestedSeries: SeriesPieOptions[] = [
    {
      type: "pie",
      name: "Asset class",
      size: "58%",
      innerSize: "34%",
      borderWidth: 1,
      borderColor: colors.surface,
      dataLabels: {
        enabled: true,
        distance: -36,
        style: {
          color: colors.textOnAccent,
          fontSize: "11px",
          fontWeight: "bold",
          textOutline: "0 1px 1px rgba(0,0,0,0.35)",
        },
        formatter(this: Point) {
          return (this.percentage ?? 0) >= 8 ? String(this.key ?? this.name ?? "") : "";
        },
      },
      states: { hover: { halo: { size: 5 }, brightness: 0.08 } },
      data: innerData,
    },
    {
      type: "pie",
      name: "Holding",
      size: "88%",
      innerSize: "60%",
      borderWidth: 1,
      borderColor: colors.surface,
      dataLabels: config.dataLabels
        ? {
            enabled: true,
            crop: false,
            distance: 28,
            connectorColor: colors.grid,
            connectorWidth: 1,
            overflow: "allow",
            softConnector: true,
            style: { color: colors.text, fontSize: "11px", fontWeight: "400", textOutline: "none" },
            useHTML: true,
            formatter(this: Point) {
              const pct = formatNumber(this.percentage ?? 0, 1);
              return `<span><b>${String(this.key ?? this.name ?? "")}</b>: <span style="color:${colors.textMuted};">${pct}%</span></span>`;
            },
          }
        : { enabled: false },
      states: { hover: { halo: { size: 6 }, brightness: 0.1 } },
      data: holdingData,
    },
  ];

  return {
    chart: { type: "pie", spacing: config.dataLabels ? [8, 76, 8, 76] : [4, 4, 4, 4] },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      pointFormatter(this: Point) {
        const name = String(this.key ?? this.name ?? "");
        const custom = this.options?.custom as
          | { assetClass?: string; displayName?: string }
          | undefined;
        const pct = formatNumber(this.percentage ?? 0, 1);
        const valueLine = valueFormatter
          ? `<div style="font-variant-numeric:tabular-nums;">${valueFormatter(this.y ?? 0)}</div>`
          : "";
        const classLine = custom?.assetClass
          ? `<div style="color:${colors.textMuted};">${custom.assetClass}</div>`
          : "";
        const displayLine = custom?.displayName && custom.displayName !== name
          ? `<div>${custom.displayName}</div>`
          : "";
        return `<b>${name}</b>${displayLine}${classLine}${valueLine}<div style="color:${colors.textMuted};">${pct}% of portfolio</div>`;
      },
    },
    plotOptions: {
      pie: {
        animation: { duration: 850 },
        center: ["50%", "50%"],
        slicedOffset: 6,
        startAngle: -90,
      },
    },
    series: hasAssetClasses ? nestedSeries : [singleSeries],
  };
}

export function allocationSliceColor(
  slice: AllocationSlice,
  index: number,
  colors: ChartColors,
): ColorString {
  return pointColor(slice, index, colors);
}
