/**
 * Pure transform: portfolio holdings -> ordered tree rows for the Grid Pro
 * parent-id tree (Asset Class -> Strategy -> Holding) with a top-level Cash
 * node. Reuses the builder's `WeightTreeRow` output contract so the grid
 * adapter (`weightsTreeGridOptions`) renders it unchanged.
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

interface Strat {
  label: string;
  weight: number;
  funds: { input: AllocationInput; weight: number }[];
}

interface Root {
  id: string;
  label: string;
  weight: number;
  /** Asset-class groups have strategies; the cash node has none. */
  strategies: Map<string, Strat> | null;
}

export function buildAllocationTree(
  holdings: AllocationInput[],
  totalValue: number,
  cashValue: number,
): WeightTreeRow[] {
  if (totalValue <= 0) return [];

  const groups = new Map<string, Root & { code: string }>();
  for (const hld of holdings) {
    const weight = hld.marketValue / totalValue;
    if (weight <= WEIGHT_FLOOR) continue;
    const code = hld.assetClass ?? "__other__";
    const acLabel = hld.assetClass
      ? (ASSET_CLASS_LABEL[hld.assetClass] ?? hld.assetClass)
      : "Other";
    const stratLabel =
      hld.strategyLabel ?? (hld.instrumentId ? "Unclassified" : "Direct equity");
    let g = groups.get(code);
    if (!g) {
      g = {
        id: `ac:${code}`,
        code,
        label: acLabel,
        weight: 0,
        strategies: new Map(),
      };
      groups.set(code, g);
    }
    g.weight += weight;
    const strategies = g.strategies as Map<string, Strat>;
    let s = strategies.get(stratLabel);
    if (!s) {
      s = { label: stratLabel, weight: 0, funds: [] };
      strategies.set(stratLabel, s);
    }
    s.weight += weight;
    s.funds.push({ input: hld, weight });
  }

  const roots: Root[] = [...groups.values()];
  if (cashValue > WEIGHT_FLOOR * totalValue) {
    roots.push({
      id: CASH_ID,
      label: "Cash",
      weight: cashValue / totalValue,
      strategies: null,
    });
  }

  const byWeightDesc = <T extends { weight: number }>(a: T, b: T) =>
    b.weight - a.weight;

  const rows: WeightTreeRow[] = [];
  let leafSeq = 0;
  for (const root of roots.sort(byWeightDesc)) {
    rows.push({
      id: root.id,
      parentId: null,
      label: root.label,
      weight: root.weight,
      instrumentId: null,
      name: null,
    });
    if (root.strategies === null) continue;
    const code = root.id.slice("ac:".length);
    for (const s of [...root.strategies.values()].sort(byWeightDesc)) {
      const stId = `st:${code}/${s.label}`;
      rows.push({
        id: stId,
        parentId: root.id,
        label: s.label,
        weight: s.weight,
        instrumentId: null,
        name: null,
      });
      for (const f of [...s.funds].sort(byWeightDesc)) {
        rows.push({
          id: `leaf:${f.input.instrumentId ?? f.input.ticker ?? `seq${leafSeq}`}`,
          parentId: stId,
          label: f.input.ticker ?? f.input.name ?? "-",
          weight: f.weight,
          instrumentId: f.input.instrumentId,
          name: f.input.name,
        });
        leafSeq += 1;
      }
    }
  }
  return rows;
}
