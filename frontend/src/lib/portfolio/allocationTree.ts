/**
 * Pure transform: portfolio holdings -> ordered tree rows for the Grid Pro
 * parent-id tree. Two levels only — Asset class (group) -> Holding (leaf) — plus
 * a top-level Cash node, mirroring the Funds universe table layout (Ticker +
 * name in the tree column, Strategy in its own column, Weight last). Reuses the
 * builder's `WeightTreeRow` output contract so the grid adapter
 * (`weightsTreeGridOptions`) renders it unchanged.
 */
import type { WeightTreeRow } from "@/lib/builder/weightsTree";

/** One portfolio holding, decoupled from the generated API type. */
export interface AllocationInput {
  ticker: string | null;
  name: string | null;
  marketValue: number;
  assetClass: string | null;
  strategyLabel: string | null;
  instrumentId: string | null;
}

const WEIGHT_FLOOR = 1e-6;
const CASH_ID = "ac:__cash__";

const ASSET_CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
};

interface Group {
  code: string;
  label: string;
  weight: number;
  holdings: { input: AllocationInput; weight: number }[];
}

export function buildAllocationTree(
  holdings: AllocationInput[],
  totalValue: number,
  cashValue: number,
): WeightTreeRow[] {
  if (totalValue <= 0) return [];

  const groups = new Map<string, Group>();
  for (const hld of holdings) {
    const weight = hld.marketValue / totalValue;
    if (weight <= WEIGHT_FLOOR) continue;
    const code = hld.assetClass ?? "__other__";
    const acLabel = hld.assetClass
      ? (ASSET_CLASS_LABEL[hld.assetClass] ?? hld.assetClass)
      : "Other";
    let g = groups.get(code);
    if (!g) {
      g = { code, label: acLabel, weight: 0, holdings: [] };
      groups.set(code, g);
    }
    g.weight += weight;
    g.holdings.push({ input: hld, weight });
  }

  // Merge cash into the root ordering so it sorts by weight alongside the
  // asset-class groups (cash renders as a childless top-level leaf).
  type Root =
    | { kind: "group"; weight: number; group: Group }
    | { kind: "cash"; weight: number };
  const roots: Root[] = [...groups.values()].map((group) => ({
    kind: "group" as const,
    weight: group.weight,
    group,
  }));
  if (cashValue > WEIGHT_FLOOR * totalValue) {
    roots.push({ kind: "cash", weight: cashValue / totalValue });
  }
  roots.sort((a, b) => b.weight - a.weight);

  const byWeightDesc = <T extends { weight: number }>(a: T, b: T) =>
    b.weight - a.weight;

  const rows: WeightTreeRow[] = [];
  let leafSeq = 0;
  for (const root of roots) {
    if (root.kind === "cash") {
      rows.push({
        id: CASH_ID,
        parentId: null,
        label: "Cash",
        weight: root.weight,
        instrumentId: null,
        name: null,
        strategy: null,
        isGroup: false,
      });
      continue;
    }
    const g = root.group;
    const acId = `ac:${g.code}`;
    rows.push({
      id: acId,
      parentId: null,
      label: g.label,
      weight: g.weight,
      instrumentId: null,
      name: null,
      strategy: null,
      isGroup: true,
    });
    for (const f of [...g.holdings].sort(byWeightDesc)) {
      rows.push({
        id: `leaf:${f.input.instrumentId ?? f.input.ticker ?? `seq${leafSeq}`}`,
        parentId: acId,
        label: f.input.ticker ?? f.input.name ?? "—",
        weight: f.weight,
        instrumentId: f.input.instrumentId,
        name: f.input.name,
        strategy: f.input.strategyLabel,
        isGroup: false,
      });
      leafSeq += 1;
    }
  }
  return rows;
}
