/**
 * Pure option builder: portfolio exposure sunburst.
 *
 * The API supplies a parent-linked tree: asset class -> fund series -> final
 * holding. Direct stocks can skip the fund series level and appear as final
 * holding leaves under asset class.
 */
import type { Options, Point, PointOptionsObject } from "highcharts";

import type { ExposureItem, PortfolioLookthrough } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

const ASSET_CLASS_LABELS: Record<string, string> = {
  alternatives: "Alternatives",
  equity: "Equity",
  fixed_income: "Fixed Income",
  ABS: "Asset-backed securities",
  "ABS-MBS": "ABS / MBS",
  "ABS-O": "Asset-backed securities",
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
  UNKNOWN: "Unclassified",
};

const ROOT_ID = "portfolio-root";
const round4 = (value: number) => parseFloat(value.toFixed(4));

export function assetClassLabel(key: string, fallback?: string | null): string {
  const trimmed = key.trim();
  return ASSET_CLASS_LABELS[trimmed.toLowerCase()]
    ?? ASSET_CLASS_LABELS[trimmed.toUpperCase()]
    ?? fallback
    ?? key;
}

export interface ExposureSunburstOptions {
  activeId?: string | null;
  rootName?: string;
  valueLabel?: string;
  onPointFocus?: (id: string) => void;
}

function nodeLabel(node: PortfolioLookthrough["tree"][number]): string {
  if (node.kind === "asset_class") return assetClassLabel(node.key, node.label);
  if (node.key === "__OTHER__") return "Other holdings";
  return node.label || node.key;
}

function leafIds(tree: PortfolioLookthrough["tree"]): Set<string> {
  const parentIds = new Set(
    tree
      .map((node) => node.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  return new Set(tree.filter((node) => !parentIds.has(node.id)).map((node) => node.id));
}

function topAssetId(
  node: PortfolioLookthrough["tree"][number],
  byId: Map<string, PortfolioLookthrough["tree"][number]>,
): string {
  let current = node;
  while (current.parent_id) {
    const parent = byId.get(current.parent_id);
    if (!parent) break;
    current = parent;
  }
  return current.id;
}

/** Suffix marking the synthetic residual leaf id under an asset-class node. */
export const OTHER_HOLDINGS_SUFFIX = "|__other__";

/** A residual leaf is at/below this % of NAV — too small to bother drawing. */
const OTHER_HOLDINGS_EPSILON = 0.005;

/** One synthetic "Other holdings" residual per asset class. */
export interface AssetResidual {
  /** Point id, `${assetNodeId}|__other__`. */
  id: string;
  /** The asset-class node this residual hangs under. */
  parentId: string;
  /** Residual % of NAV = true asset total − sampled top-N leaves. */
  valuePct: number;
}

/**
 * The tree carries only a sampled subset of holdings per asset class (e.g. the
 * top-25 largest positions), while `assetItems` holds the TRUE dimension
 * totals. This computes the per-asset-class residual (`total − Σ sampled
 * leaves`) so both the sunburst arc AND the drill table can render an identical
 * "Other holdings" node — keeping the chart, the table rows and the header
 * total in agreement. Residuals at/below the epsilon are omitted.
 */
export function computeAssetResiduals(
  tree: PortfolioLookthrough["tree"],
  assetItems: ExposureItem[],
): AssetResidual[] {
  const byId = new Map(tree.map((node) => [node.id, node]));
  const leaves = leafIds(tree);
  const assetNodes = tree.filter((node) => !node.parent_id);
  const assetTotals = new Map(
    assetItems.map((item) => [item.key.trim().toUpperCase(), item.total_pct]),
  );
  const leafSumByAsset = new Map<string, number>();
  for (const node of tree) {
    if (!leaves.has(node.id)) continue;
    const topId = topAssetId(node, byId);
    leafSumByAsset.set(topId, (leafSumByAsset.get(topId) ?? 0) + node.value_pct);
  }
  const residuals: AssetResidual[] = [];
  for (const node of assetNodes) {
    const total = assetTotals.get(node.key.trim().toUpperCase());
    if (total === undefined) continue;
    const sampled = leafSumByAsset.get(node.id) ?? 0;
    const residual = round4(Math.max(0, total - sampled));
    if (residual <= OTHER_HOLDINGS_EPSILON) continue;
    residuals.push({
      id: `${node.id}${OTHER_HOLDINGS_SUFFIX}`,
      parentId: node.id,
      valuePct: residual,
    });
  }
  return residuals;
}

export function buildHcExposureSunburstOption(
  tree: PortfolioLookthrough["tree"],
  assetItems: ExposureItem[],
  colors: ChartColors,
  opts: ExposureSunburstOptions = {},
): Options {
  const byId = new Map(tree.map((node) => [node.id, node]));
  const leaves = leafIds(tree);
  const assetNodes = tree.filter((node) => !node.parent_id);
  const colorByAsset = new Map(
    assetNodes.map((node, index) => [
      node.id,
      colors.categories[index % colors.categories.length],
    ]),
  );
  const assetTotals = new Map(
    assetItems.map((item) => [
      item.key.trim().toUpperCase(),
      { total: item.total_pct, label: assetClassLabel(item.key, item.label) },
    ]),
  );

  // The tree only carries a sampled subset of holdings per asset class (e.g.
  // the top-25 largest positions), but `assetTotals` above holds the true
  // dimension totals. Left alone, each asset-class arc would only be sized by
  // the sampled leaves it contains, disagreeing with the true total shown in
  // its own tooltip and in the exposure table. A synthetic "Other holdings"
  // residual leaf per asset class closes the gap so the arc sums to the true
  // total — computed by the shared helper so the drill table renders the
  // identical node (see ExposureSunburstGrid).
  const residualData: PointOptionsObject[] = computeAssetResiduals(
    tree,
    assetItems,
  ).map((residual) => ({
    id: residual.id,
    parent: residual.parentId,
    name: "Other holdings",
    value: residual.valuePct,
    color: colors.barMute,
    custom: {
      rawKey: byId.get(residual.parentId)?.key ?? "",
      kind: "other_holdings",
      valuePct: residual.valuePct,
    },
  }));

  const data: PointOptionsObject[] = [
    {
      id: "portfolio-root",
      parent: "",
      name: opts.rootName ?? "Portfolio",
      color: colors.surface,
      custom: {
        valuePct: assetItems.reduce((sum, item) => sum + item.total_pct, 0),
      },
    },
    ...tree.map((node) => {
      const topId = topAssetId(node, byId);
      const assetTotal = node.kind === "asset_class"
        ? assetTotals.get(node.key.trim().toUpperCase())
        : undefined;
      return {
        id: node.id,
        parent: node.parent_id ?? "portfolio-root",
        name: assetTotal?.label ?? nodeLabel(node),
        value: leaves.has(node.id) ? round4(node.value_pct) : undefined,
        color: colorByAsset.get(topId),
        ...(node.id === opts.activeId
          ? { borderColor: colors.accent, borderWidth: 3 }
          : {}),
        custom: {
          rawKey: node.key,
          kind: node.kind,
          valuePct: assetTotal?.total ?? node.value_pct,
        },
      };
    }),
    ...residualData,
  ];

  return {
    chart: {
      type: "sunburst",
      backgroundColor: "transparent",
      spacing: [24, 18, 18, 18],
    },
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
        const value = point.options.custom?.valuePct ?? 0;
        const note = point.options.custom?.kind === "other_holdings"
          ? `<br/><span style="color:${colors.textMuted}">Holdings beyond the top-25 sample</span>`
          : "";
        return `<div style="font-size:12px"><b>${point.name}</b><br/>${formatNumber(
          value,
          2,
        )}${opts.valueLabel ?? "% of NAV"}${note}</div>`;
      },
    },
    plotOptions: {
      sunburst: {
        borderColor: colors.surface,
        borderWidth: 1,
        cursor: "pointer",
        point: {
          events: {
            click() {
              const id = (this as Point).options.id;
              if (id && id !== ROOT_ID) opts.onPointFocus?.(id);
            },
            mouseOver() {
              const id = (this as Point).options.id;
              if (id && id !== ROOT_ID) opts.onPointFocus?.(id);
            },
          },
        },
        dataLabels: {
          formatter() {
            const point = (
              this as unknown as {
                point: {
                  name: string;
                  options: { custom?: { kind?: string } };
                };
              }
            ).point;
            return point.name;
          },
        },
      },
    },
    series: [
      {
        type: "sunburst",
        name: "Exposure",
        allowDrillToNode: true,
        levelIsConstant: false,
        size: "92%",
        data,
        levels: [
          {
            level: 1,
            dataLabels: { enabled: false },
          },
          {
            level: 2,
            colorByPoint: true,
            dataLabels: {
              enabled: true,
              rotationMode: "parallel",
              style: {
                color: colors.textOnAccent,
                fontSize: "11px",
                fontWeight: "bold",
                textOutline: "none",
              },
            },
          },
          {
            level: 3,
            dataLabels: {
              enabled: true,
              rotationMode: "circular",
              style: {
                color: colors.textOnAccent,
                fontSize: "10px",
                textOutline: "none",
              },
            },
          },
          {
            level: 4,
            dataLabels: {
              enabled: false,
            },
          },
        ],
      },
    ],
  };
}
