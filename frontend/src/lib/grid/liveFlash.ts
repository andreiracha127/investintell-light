/**
 * Pure mapping from a live-tick direction to the CSS flash class applied to a
 * grid "last" cell. Kept tiny and side-effect-free so it can be unit-tested
 * without a DOM; the DOM toggling (reflow re-trigger) lives in the component.
 *
 * Classes are defined in `grid-theme.css` (`.ix-grid-flash-up` / `-down`).
 */
export type TickDir = 1 | -1 | 0;

/**
 * Flash class names, shared so the helper and the DOM-toggling effect can't
 * drift. Matched as literals by `grid-theme.css` (CSS can't import these).
 */
export const FLASH_UP = "ix-grid-flash-up";
export const FLASH_DOWN = "ix-grid-flash-down";

/** 1 → up, -1 → down, 0 (unchanged) → no flash. */
export function flashClassForDir(dir: TickDir): string | null {
  if (dir === 1) return FLASH_UP;
  if (dir === -1) return FLASH_DOWN;
  return null;
}
