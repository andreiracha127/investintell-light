/**
 * Builder universe model — the client-side asset list the user assembles
 * before optimizing. Each entry carries the display label (the optimize
 * response echoes only the bare ref, so labels are resolved client-side
 * via `assetKey`).
 */
import type { BuilderAssetRef, BuilderObjective } from "@/lib/api/client";

export type UniverseAsset =
  | { kind: "fund"; id: string; ticker: string | null; name: string }
  | { kind: "equity"; ticker: string };

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
