/**
 * Pure option builder: consolidated look-through treemap (Highcharts `treemap`,
 * registered in the Core wrapper).
 *
 * One parent tile per exposure bucket (asset class / sector / currency /
 * issuer), sized by its total portfolio weight and colored from the categorical
 * palette (Cash → muted grey). Tile area is total exposure; direct/indirect is
 * intentionally not split here because the portfolio view is about final
 * look-through exposure.
 *
 * Chrome (tooltip styling) is owned by the global Graphite theme; the builder
 * sets only the series, token colors, and percent formatting.
 */
import type { Options, PointOptionsObject } from "highcharts";

import type { ExposureItem, PortfolioLookthrough } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

const isCash = (label: string) => label.trim().toLowerCase() === "cash";
const round2 = (v: number) => parseFloat(v.toFixed(4));

const ASSET_CLASS_LABELS: Record<string, string> = {
  ABS: "Asset-backed securities",
  "ABS-MBS": "ABS / MBS",
  C: "Cash and equivalents",
  CE: "Cash and equivalents",
  CMBS: "Commercial MBS",
  CORP: "Corporate bonds",
  DBT: "Debt",
  EC: "Equity",
  EP: "Preferred equity",
  MBS: "Mortgage-backed securities",
  RA: "Real assets",
  RE: "Real estate",
  STIV: "Short-term investments",
  UST: "U.S. Treasuries",
};

export interface ExposureTreemapConfig {
  dimension?: string | null;
  tree?: PortfolioLookthrough["tree"];
}

export function exposureBucketLabel(item: ExposureItem, dimension?: string | null): string {
  const raw = item.label ?? item.key;
  if (dimension === "asset_class") {
    const key = item.key.trim().toUpperCase();
    return ASSET_CLASS_LABELS[key] ?? raw;
  }
  return raw;
}

/**
 * Build a look-through treemap for one exposure dimension.
 *
 * @param items  Exposure items for the active dimension (percent-point values).
 * @param colors Design-token color bag (from chartColors()).
 * @param config Opt-in behavior (e.g. zoomable traversal).
 */
export function buildHcExposureTreemapOption(
  items: ExposureItem[],
  colors: ChartColors,
  config: ExposureTreemapConfig = {},
): Options {
  if (config.dimension === "asset_class" && config.tree && config.tree.length > 0) {
    return buildTreeExposureTreemapOption(config.tree, colors);
  }

  const sorted = [...items]
    .filter((item) => item.total_pct > 0)
    .sort((a, b) => b.total_pct - a.total_pct);

  const data: PointOptionsObject[] = [];
  sorted.forEach((item, i) => {
    const label = exposureBucketLabel(item, config.dimension);
    const color = isCash(label)
      ? colors.barMute
      : colors.categories[i % colors.categories.length];
    data.push({
      id: `bucket-${i}`,
      name: label,
      value: round2(item.total_pct),
      color,
      custom: { rawKey: item.key },
    });
  });

  return {
    chart: { type: "treemap" },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              value?: number;
              options: { custom?: { rawKey?: string } };
            };
          }
        ).point;
        const rawKey = point.options.custom?.rawKey;
        const value = point.value ?? 0;
        if (rawKey && rawKey !== point.name) {
          return `<div style="font-size:12px"><b>${point.name}</b> <span style="opacity:.65">(${rawKey})</span><br/>${formatNumber(
            value,
            2,
          )}% of portfolio</div>`;
        }
        return `<div style="font-size:12px"><b>${point.name}</b><br/>${formatNumber(
          value,
          2,
        )}% of portfolio</div>`;
      },
    },
    series: [
      {
        type: "treemap",
        name: "Exposure",
        layoutAlgorithm: "squarified",
        allowTraversingTree: false,
        animationLimit: 1000,
        // Header breadcrumb on the bucket level so zoom-out is one click. Only
        // meaningful when traversal is on; Highcharts ignores it otherwise.
        traverseUpButton: { position: { align: "left", x: 0, y: 0 } },
        levels: [
          {
            level: 1,
            borderWidth: 3,
            borderColor: colors.surface,
            layoutAlgorithm: "squarified",
            dataLabels: {
              enabled: true,
              align: "left",
              verticalAlign: "top",
              style: {
                color: colors.textOnAccent,
                fontWeight: "bold",
                fontSize: "11px",
                textOutline: "none",
              },
            },
          },
        ],
        data,
      },
    ],
  };
}

function treeNodeLabel(node: PortfolioLookthrough["tree"][number]): string {
  if (node.kind === "asset_class") {
    const key = node.key.trim().toUpperCase();
    return ASSET_CLASS_LABELS[key] ?? node.label;
  }
  return node.label;
}

function buildTreeExposureTreemapOption(
  tree: PortfolioLookthrough["tree"],
  colors: ChartColors,
): Options {
  const parentIds = new Set(
    tree
      .map((node) => node.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  const topLevel = tree.filter((node) => !node.parent_id);
  const colorByTopId = new Map(
    topLevel.map((node, i) => [
      node.id,
      isCash(treeNodeLabel(node))
        ? colors.barMute
        : colors.categories[i % colors.categories.length],
    ]),
  );

  const topAncestorColor = (node: PortfolioLookthrough["tree"][number]) => {
    if (!node.parent_id) return colorByTopId.get(node.id);
    const parent = tree.find((candidate) => candidate.id === node.parent_id);
    if (!parent) return undefined;
    if (!parent.parent_id) return colorByTopId.get(parent.id);
    const grandparent = tree.find((candidate) => candidate.id === parent.parent_id);
    return grandparent ? colorByTopId.get(grandparent.id) : undefined;
  };

  const data: PointOptionsObject[] = tree.map((node) => {
    const hasChildren = parentIds.has(node.id);
    return {
      id: node.id,
      parent: node.parent_id ?? undefined,
      name: treeNodeLabel(node),
      value: hasChildren ? undefined : round2(node.value_pct),
      color: topAncestorColor(node),
      custom: { rawKey: node.key, valuePct: node.value_pct, kind: node.kind },
    };
  });

  return {
    chart: { type: "treemap" },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              options: {
                custom?: { rawKey?: string; valuePct?: number; kind?: string };
              };
            };
          }
        ).point;
        const rawKey = point.options.custom?.rawKey;
        const value = point.options.custom?.valuePct ?? 0;
        const suffix = rawKey && rawKey !== point.name ? ` <span style="opacity:.65">(${rawKey})</span>` : "";
        return `<div style="font-size:12px"><b>${point.name}</b>${suffix}<br/>${formatNumber(
          value,
          2,
        )}% of portfolio</div>`;
      },
    },
    series: [
      {
        type: "treemap",
        name: "Exposure",
        layoutAlgorithm: "squarified",
        allowTraversingTree: true,
        animationLimit: 1000,
        traverseUpButton: { position: { align: "left", x: 0, y: 0 } },
        levels: [
          {
            level: 1,
            borderWidth: 3,
            borderColor: colors.surface,
            layoutAlgorithm: "squarified",
            dataLabels: {
              enabled: true,
              align: "left",
              verticalAlign: "top",
              style: {
                color: colors.textOnAccent,
                fontWeight: "bold",
                fontSize: "11px",
                textOutline: "none",
              },
            },
          },
          {
            level: 2,
            borderWidth: 2,
            borderColor: colors.surface,
            dataLabels: {
              enabled: true,
              style: {
                color: colors.textOnAccent,
                fontWeight: "bold",
                fontSize: "10.5px",
                textOutline: "none",
              },
            },
          },
          {
            level: 3,
            borderWidth: 1,
            borderColor: colors.surface,
            dataLabels: {
              enabled: true,
              style: {
                color: colors.textOnAccent,
                fontSize: "10px",
                textOutline: "none",
              },
            },
          },
        ],
        data,
      },
    ],
  };
}
