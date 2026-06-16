/**
 * Pure transform: a flat list of optimizer weights → ordered tree rows for the
 * Grid Pro parent-id tree (Asset Class → Strategy → Fund). Zero-weight
 * positions are dropped; parent rows carry the aggregated weight of their
 * children. Leaves carry the fund `instrumentId` (for the dossier link); parent
 * rows do not. Funds without an asset_class fall under "Other".
 */

/** One optimizer position, decoupled from the generated API type. */
export interface WeightInput {
  kind: "fund" | "equity";
  instrumentId: string | null;
  ticker: string | null;
  name: string | null;
  weight: number;
  assetClass: string | null;
  strategyLabel: string | null;
}

/** A row for the Grid Pro parent-id tree. */
export interface WeightTreeRow {
  id: string;
  parentId: string | null;
  label: string;
  weight: number;
  /** Fund instrument id for the dossier link; null for parent/aggregate rows. */
  instrumentId: string | null;
}

const WEIGHT_FLOOR = 1e-6;

const ASSET_CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
};

export function buildWeightsTree(weights: WeightInput[]): WeightTreeRow[] {
  const kept = weights.filter((w) => w.weight > WEIGHT_FLOOR);

  // Group by asset_class code → strategy label, summing weights.
  interface Strat {
    label: string;
    weight: number;
    funds: WeightInput[];
  }
  interface Group {
    code: string; // "equity" | ... | "__other__"
    label: string;
    weight: number;
    strategies: Map<string, Strat>;
  }
  const groups = new Map<string, Group>();

  for (const w of kept) {
    const code = w.assetClass ?? "__other__";
    const acLabel = w.assetClass
      ? (ASSET_CLASS_LABEL[w.assetClass] ?? w.assetClass)
      : "Other";
    const stratLabel = w.strategyLabel ?? "Unclassified";
    let g = groups.get(code);
    if (!g) {
      g = { code, label: acLabel, weight: 0, strategies: new Map() };
      groups.set(code, g);
    }
    g.weight += w.weight;
    let s = g.strategies.get(stratLabel);
    if (!s) {
      s = { label: stratLabel, weight: 0, funds: [] };
      g.strategies.set(stratLabel, s);
    }
    s.weight += w.weight;
    s.funds.push(w);
  }

  const byWeightDesc = <T extends { weight: number }>(a: T, b: T) =>
    b.weight - a.weight;

  const rows: WeightTreeRow[] = [];
  let leafSeq = 0; // stable, deterministic unique suffix for identity-less leaves
  for (const g of [...groups.values()].sort(byWeightDesc)) {
    const acId = `ac:${g.code}`;
    rows.push({ id: acId, parentId: null, label: g.label, weight: g.weight, instrumentId: null });
    for (const s of [...g.strategies.values()].sort(byWeightDesc)) {
      const stId = `st:${g.code}/${s.label}`;
      rows.push({ id: stId, parentId: acId, label: s.label, weight: s.weight, instrumentId: null });
      for (const f of [...s.funds].sort(byWeightDesc)) {
        rows.push({
          id: `leaf:${f.instrumentId ?? f.ticker ?? f.name ?? `seq${leafSeq}`}`,
          parentId: stId,
          label: f.ticker ?? f.name ?? "—",
          weight: f.weight,
          instrumentId: f.kind === "fund" ? f.instrumentId : null,
        });
        leafSeq += 1;
      }
    }
  }
  return rows;
}
