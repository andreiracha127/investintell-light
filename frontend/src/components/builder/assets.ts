/**
 * Builder universe model — the client-side asset list the user assembles
 * before optimizing. Each entry carries the display label (the optimize
 * response echoes only the bare ref, so labels are resolved client-side
 * via `assetKey`).
 */
import type {
  BuilderAssetRef,
  BuilderObjective,
  BuilderUniverseSpec,
  FundsQuery,
  SymbolSearchResult,
} from "@/lib/api/client";

export type UniverseAsset =
  | { kind: "fund"; id: string; ticker: string | null; name: string }
  | { kind: "equity"; ticker: string };

/**
 * Map a symbol-search hit to a universe asset. A hit carrying an
 * `instrument_id` is a synced fund (priced by NAV); otherwise it is an equity
 * ticker (priced by eod_prices). This is what lets one autocomplete add both
 * stocks and funds without the user knowing the distinction.
 */
export function symbolToAsset(item: SymbolSearchResult): UniverseAsset {
  if (item.instrument_id) {
    return {
      kind: "fund",
      id: item.instrument_id,
      ticker: item.symbol,
      name: item.name ?? item.symbol,
    };
  }
  return { kind: "equity", ticker: item.symbol.toUpperCase() };
}

/** Stable identity for a universe asset or a response/weight asset ref. */
export function assetKey(asset: UniverseAsset | BuilderAssetRef): string {
  return asset.kind === "fund"
    ? `fund:${asset.id}`
    : `equity:${asset.ticker.toUpperCase()}`;
}

export function toRef(asset: UniverseAsset): BuilderAssetRef {
  return asset.kind === "fund"
    ? { kind: "fund", id: asset.id }
    : { kind: "equity", ticker: asset.ticker };
}

/** Short display label: the ticker when known, else the fund name. */
export function assetTicker(asset: UniverseAsset): string {
  if (asset.kind === "equity") return asset.ticker;
  return asset.ticker ?? asset.name;
}

/** Secondary label (full name) — empty for ad-hoc equities. */
export function assetName(asset: UniverseAsset): string {
  return asset.kind === "fund" ? asset.name : "";
}

/* ── Fund-universe optimization (filter + rank, no explicit list) ──────────── */

export type UniverseRankBy =
  | "aum_usd"
  | "sharpe_1y"
  | "return_1y"
  | "expense_ratio"
  | "volatility_1y"
  | "max_drawdown_1y";

/** UI draft for a universe spec — numeric fields are raw text/whole numbers. */
export interface UniverseDraft {
  fundType: "" | "etf" | "mmf" | "mutual_fund";
  assetClass: "" | "equity" | "fixed_income" | "cash" | "alternatives";
  /** AUM floor in USD millions (raw text). */
  aumMinM: string;
  /** Expense-ratio ceiling in percent (raw text). */
  expenseMaxPct: string;
  rankBy: UniverseRankBy;
  rankDir: "asc" | "desc";
  /** How many top-ranked candidates the optimizer runs over (2–50). */
  maxAssets: number;
}

export const RANK_BY_LABELS: Record<UniverseRankBy, string> = {
  aum_usd: "AUM",
  sharpe_1y: "Sharpe (1y)",
  return_1y: "Return (1y)",
  expense_ratio: "Expense ratio",
  volatility_1y: "Volatility (1y)",
  max_drawdown_1y: "Max drawdown (1y)",
};

export function defaultUniverseDraft(): UniverseDraft {
  return {
    fundType: "",
    assetClass: "",
    aumMinM: "",
    expenseMaxPct: "",
    rankBy: "aum_usd",
    rankDir: "desc",
    maxAssets: 30,
  };
}

/** Parse a non-empty, finite, non-negative number; else undefined. */
function parsePositiveNum(text: string): number | undefined {
  if (text.trim() === "") return undefined;
  const v = Number(text);
  return Number.isFinite(v) && v >= 0 ? v : undefined;
}

/** Shared filter fields (AUM in $, expense as a fraction) for both the API
 * spec and the live match-count query. */
function universeFilters(draft: UniverseDraft): {
  fund_type?: "etf" | "mmf" | "mutual_fund";
  asset_class?: "equity" | "fixed_income" | "cash" | "alternatives";
  aum_min?: number;
  expense_ratio_max?: number;
} {
  const aum = parsePositiveNum(draft.aumMinM);
  const exp = parsePositiveNum(draft.expenseMaxPct);
  return {
    ...(draft.fundType ? { fund_type: draft.fundType } : {}),
    ...(draft.assetClass ? { asset_class: draft.assetClass } : {}),
    ...(aum !== undefined ? { aum_min: aum * 1e6 } : {}),
    ...(exp !== undefined ? { expense_ratio_max: exp / 100 } : {}),
  };
}

export function universeDraftToSpec(
  draft: UniverseDraft,
  includeIds?: readonly string[],
): BuilderUniverseSpec {
  return {
    ...universeFilters(draft),
    rank_by: draft.rankBy,
    rank_dir: draft.rankDir,
    max_assets: draft.maxAssets,
    // Broad-universe mode is opt-in elsewhere; ranked mode keeps these at their
    // defaults (the backend ignores max_positions/min_pair_overlap unless
    // broad_universe is true).
    broad_universe: false,
    max_positions: draft.maxAssets,
    min_pair_overlap: 252,
    ...(includeIds && includeIds.length >= 2
      ? { include_instrument_ids: [...includeIds] }
      : {}),
  };
}

/** A /funds query that counts how many funds match the draft filters. */
export function universeDraftToCountQuery(draft: UniverseDraft): FundsQuery {
  return {
    ...universeFilters(draft),
    sort: draft.rankBy,
    dir: draft.rankDir,
    page: 1,
    page_size: 1,
  };
}

/** A /funds query that fetches the top-`pageSize` ranked funds the optimizer
 * would run over — same filters + rank as the count query, larger page. */
export function universeDraftToPreviewQuery(
  draft: UniverseDraft,
  pageSize: number,
): FundsQuery {
  return {
    ...universeFilters(draft),
    sort: draft.rankBy,
    dir: draft.rankDir,
    page: 1,
    page_size: pageSize,
  };
}

export const OBJECTIVES: {
  value: BuilderObjective;
  label: string;
  description: string;
}[] = [
  {
    value: "min_cvar",
    label: "Min CVaR (default)",
    description:
      "Minimizes expected loss in the worst 5% of historical scenarios (Rockafellar–Uryasev).",
  },
  {
    value: "min_vol",
    label: "Min volatility",
    description: "Minimizes portfolio variance under the Ledoit-Wolf covariance.",
  },
  {
    value: "erc",
    label: "Equal risk contribution",
    description: "Each asset contributes the same share of total portfolio risk.",
  },
  {
    value: "max_diversification",
    label: "Max diversification",
    description:
      "Maximizes the ratio of weighted asset vols to portfolio vol (Choueifaty ratio).",
  },
  {
    value: "equal_weight",
    label: "Equal weight",
    description: "1/N across the universe, then capped and renormalized.",
  },
  {
    value: "bl_utility",
    label: "BL max utility",
    description:
      "Mean-variance utility on the Black-Litterman posterior — requires views to tilt away from market weights.",
  },
];
