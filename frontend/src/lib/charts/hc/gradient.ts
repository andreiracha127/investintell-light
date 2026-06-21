/**
 * Small pure helpers for Highcharts fills/effects. Keep them DOM-free so the
 * option builders stay unit-testable in node.
 */
import type { GradientColorObject } from "highcharts";

/** Convert a hex color (#rgb or #rrggbb) to an `rgba(...)` string. */
export function withAlpha(color: string, alpha: number): string {
  const hex = color.trim();
  if (hex[0] !== "#") return color;
  let r = 0;
  let g = 0;
  let b = 0;
  if (hex.length === 4) {
    r = parseInt(hex[1] + hex[1], 16);
    g = parseInt(hex[2] + hex[2], 16);
    b = parseInt(hex[3] + hex[3], 16);
  } else if (hex.length >= 7) {
    r = parseInt(hex.slice(1, 3), 16);
    g = parseInt(hex.slice(3, 5), 16);
    b = parseInt(hex.slice(5, 7), 16);
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Vertical fill: solid-ish at the top fading toward the axis. Gives columns and
 * areas depth instead of the flat "spreadsheet" look.
 */
export function verticalFill(
  color: string,
  topAlpha = 0.95,
  bottomAlpha = 0.35,
): GradientColorObject {
  return {
    linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
    stops: [
      [0, withAlpha(color, topAlpha)],
      [1, withAlpha(color, bottomAlpha)],
    ],
  };
}
