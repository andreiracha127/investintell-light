/**
 * Input-parsing helpers — the only place raw user text becomes numbers.
 *
 * Kept separate from `format.ts` (display) so the concerns stay distinct.
 */

/**
 * Parse a user-typed decimal string that may use either a period or a comma
 * as the decimal separator (e.g. "40,5" → 40.5, "40.5" → 40.5).
 *
 * Only a single separator character is normalised; thousand-separator grouping
 * is not supported (users are expected to type plain numeric strings).
 *
 * Returns `NaN` for empty or non-numeric input, matching the contract of
 * `Number()` so callers can use `Number.isFinite()` to gate submission.
 */
export function parseDecimal(text: string): number {
  const normalised = text.trim().replace(",", ".");
  return Number(normalised);
}
