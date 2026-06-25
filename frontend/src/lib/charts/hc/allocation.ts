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
  /** Total NAV used for "% NAV" labels. Falls back to the sum of slices. */
  navTotal?: number;
  /** Asset-class label currently expanded in two-level drilldown mode. */
  activeAssetClass?: string | null;
  /** Show only asset classes until the user expands one class into holdings. */
  drilldown?: boolean;
  /** Render leader labels with each point's NAV share. */
  navDataLabels?: boolean;
  /** Called when an asset-class point is clicked in drilldown mode. */
  onAssetClassClick?: (assetClass: string | null) => void;
  valueFormatter?: (value: number) => string;
}

type AllocationPointCustom = {
  assetClass?: string;
  displayName?: string;
  isAssetClass?: boolean;
  navPct?: number;
};

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

function navPct(value: number, total: number): number {
  return total > 0 ? (value / total) * 100 : 0;
}

function navPctLabel(point: Point, colors: ChartColors): string {
  const custom = point.options.custom as AllocationPointCustom | undefined;
  const pct = custom?.navPct ?? point.percentage ?? 0;
  const name = String(point.key ?? point.name ?? "");
  return `<span>${name}</span><br/><span style="color:${colors.textMuted};font-size:10px">${formatNumber(pct, 1)}% NAV</span>`;
}

export function buildHcAllocationOption(
  slices: AllocationSlice[],
  colors: ChartColors,
  config: AllocationConfig = {},
): Options {
  const innerSize = config.innerSize ?? "62%";
  const valueFormatter = config.valueFormatter;
  const hasAssetClasses = slices.some((slice) => slice.assetClass);
  const totalForPct = config.navTotal ?? slices.reduce((sum, slice) => sum + slice.value, 0);
  const holdingData = slices.map((slice, i) => ({
    name: slice.name,
    y: slice.value,
    color: pointColor(slice, i, colors),
    custom: {
      assetClass: assetClassLabel(slice.assetClass),
      displayName: slice.displayName,
      navPct: navPct(slice.value, totalForPct),
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
    custom: {
      assetClass: name,
      isAssetClass: true,
      navPct: navPct(item.value, totalForPct),
    },
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

  const activeAssetClass = config.activeAssetClass ?? null;
  const drilldown = config.drilldown ?? false;
  const showSecondLevel = !drilldown || Boolean(activeAssetClass);
  const secondLevelData = activeAssetClass
    ? holdingData.filter((point) => point.custom.assetClass === activeAssetClass)
    : holdingData;

  const innerLabelOptions: SeriesPieOptions["dataLabels"] = config.navDataLabels
    ? {
        enabled: true,
        crop: false,
        distance: 16,
        connectorColor: colors.grid,
        connectorWidth: 1,
        overflow: "allow",
        softConnector: true,
        useHTML: true,
        style: {
          color: colors.text,
          fontSize: "11px",
          fontWeight: "700",
          textOutline: "none",
        },
        formatter(this: Point) {
          return navPctLabel(this, colors);
        },
      }
    : {
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
      };

  const nestedSeries: SeriesPieOptions[] = [
    {
      type: "pie",
      name: "Asset class",
      size: showSecondLevel ? "58%" : "82%",
      innerSize: showSecondLevel ? "34%" : "52%",
      borderWidth: 1,
      borderColor: colors.surface,
      dataLabels: innerLabelOptions,
      states: { hover: { halo: { size: 5 }, brightness: 0.08 } },
      point: {
        events: {
          click() {
            if (!drilldown || !config.onAssetClassClick) return;
            const custom = this.options.custom as AllocationPointCustom | undefined;
            const label = custom?.assetClass ?? String(this.name ?? "");
            config.onAssetClassClick(label === activeAssetClass ? null : label);
          },
        },
      },
      data: innerData,
    },
  ];

  if (showSecondLevel) {
    nestedSeries.push({
      type: "pie",
      name: "Holding",
      size: "88%",
      innerSize: "60%",
      borderWidth: 1,
      borderColor: colors.surface,
      dataLabels: config.dataLabels || (drilldown && Boolean(activeAssetClass))
        ? {
            enabled: true,
            crop: false,
            distance: 24,
            connectorColor: colors.grid,
            connectorWidth: 1,
            overflow: "allow",
            softConnector: true,
            style: { color: colors.text, fontSize: "11px", fontWeight: "400", textOutline: "none" },
            useHTML: true,
            formatter(this: Point) {
              const custom = this.options.custom as AllocationPointCustom | undefined;
              const pct = custom?.navPct ?? this.percentage ?? 0;
              const name = String(this.key ?? this.name ?? "");
              return `<span><b>${name}</b>: <span style="color:${colors.textMuted};">${formatNumber(pct, 1)}% NAV</span></span>`;
            },
          }
        : { enabled: false },
      states: { hover: { halo: { size: 6 }, brightness: 0.1 } },
      data: secondLevelData,
    });
  }

  return {
    chart: {
      type: "pie",
      spacing: config.dataLabels || config.navDataLabels ? [10, 58, 10, 58] : [4, 4, 4, 4],
    },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      pointFormatter(this: Point) {
        const name = String(this.key ?? this.name ?? "");
        const custom = this.options?.custom as AllocationPointCustom | undefined;
        const pct = formatNumber(custom?.navPct ?? this.percentage ?? 0, 1);
        const valueLine = valueFormatter
          ? `<div style="font-variant-numeric:tabular-nums;">${valueFormatter(this.y ?? 0)}</div>`
          : "";
        const classLine = custom?.assetClass
          ? `<div style="color:${colors.textMuted};">${custom.assetClass}</div>`
          : "";
        const displayLine = custom?.displayName && custom.displayName !== name
          ? `<div>${custom.displayName}</div>`
          : "";
        const pctLabel = config.navTotal ? "of NAV" : "of portfolio";
        return `<b>${name}</b>${displayLine}${classLine}${valueLine}<div style="color:${colors.textMuted};">${pct}% ${pctLabel}</div>`;
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
