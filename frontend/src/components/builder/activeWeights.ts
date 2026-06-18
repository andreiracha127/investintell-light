"use client";

import type { BuilderAssetRef, WeightOut } from "@/lib/api/client";

/** Weights at or below this are solver noise and invalid for analytics APIs. */
export const ACTIVE_WEIGHT_FLOOR = 1e-6;

export interface ActiveWeight {
  asset: BuilderAssetRef;
  weight: number;
  source: WeightOut;
}

export interface ActiveWeights {
  positions: ActiveWeight[];
  dropped: number;
  total: number;
  isValid: boolean;
}

export function buildActiveWeights(weights: readonly WeightOut[]): ActiveWeights {
  const active = weights.filter((weight) => weight.weight > ACTIVE_WEIGHT_FLOOR);
  const total = active.reduce((sum, weight) => sum + weight.weight, 0);
  const positions =
    total > 0
      ? active.map((weight) => ({
          asset: weight.asset,
          weight: weight.weight / total,
          source: weight,
        }))
      : [];

  return {
    positions,
    dropped: weights.length - active.length,
    total,
    isValid: positions.length >= 2,
  };
}
