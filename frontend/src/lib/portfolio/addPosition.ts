/**
 * Pure helpers for adding to a portfolio by dollar amount.
 *
 * Amount-mode adds ACCUMULATE onto an existing holding: the new quantity is the
 * current quantity plus amount/spot, and the average cost becomes the
 * quantity-weighted blend of the old cost and the new lot's price. Used by both
 * the portfolio positions table and the stocks "Add to portfolio" popover so
 * the math lives in one tested place.
 *
 * No DOM, no network — safe to unit test in node. Callers validate inputs
 * (amount > 0, spot > 0) before calling.
 */

export interface ExistingHolding {
  quantity: number;
  /** Average acquisition price, or null when unknown. */
  acqPrice: number | null;
  /** Latest close, used as the spot fallback when no price is typed. */
  lastClose: number | null;
}

/** Spot price for Amount mode: an explicit price wins, else the last close. */
export function resolveSpot(
  explicitPrice: number | null,
  existing: ExistingHolding | null,
): number | null {
  if (explicitPrice != null && explicitPrice > 0) return explicitPrice;
  const last = existing?.lastClose ?? null;
  return last != null && last > 0 ? last : null;
}

/**
 * Quantity-weighted average cost after adding `addedQty` shares at `lotPrice`.
 * Returns null when the prior cost is unknown (we never invent a basis).
 */
export function weightedAvgCost(
  existing: ExistingHolding,
  addedQty: number,
  lotPrice: number,
): number | null {
  if (existing.acqPrice == null) return null;
  const total = existing.quantity + addedQty;
  if (total <= 0) return existing.acqPrice;
  return (existing.quantity * existing.acqPrice + addedQty * lotPrice) / total;
}

export interface AccumulateResult {
  /** Resulting position quantity to PUT. */
  quantity: number;
  /** Resulting acquisition price to PUT. */
  acqPrice: number | null;
}

/**
 * Accumulate `addedQty` shares (bought at `lotPrice`, or null when unknown)
 * onto an existing holding. Shared by both Shares and Amount entry modes:
 *  - no holding  → opens a new position at `lotPrice`;
 *  - lotPrice null (no price for the new lot) → keeps the prior average cost;
 *  - otherwise   → quantity summed, average cost blended by quantity.
 */
export function accumulate(
  addedQty: number,
  lotPrice: number | null,
  existing: ExistingHolding | null,
): AccumulateResult {
  if (!existing) return { quantity: addedQty, acqPrice: lotPrice };
  const quantity = existing.quantity + addedQty;
  if (lotPrice == null) return { quantity, acqPrice: existing.acqPrice };
  return { quantity, acqPrice: weightedAvgCost(existing, addedQty, lotPrice) };
}

export interface AmountAdd extends AccumulateResult {
  /** Shares this contribution adds (amount / spot). */
  addedQuantity: number;
}

/**
 * Build the resulting position from an Amount-mode add. With an existing
 * holding the contribution accumulates onto it (quantity summed, cost blended);
 * otherwise it opens a new position bought at `spot`.
 */
export function buildAmountAdd(
  amount: number,
  spot: number,
  existing: ExistingHolding | null,
): AmountAdd {
  const addedQuantity = amount / spot;
  return { ...accumulate(addedQuantity, spot, existing), addedQuantity };
}
