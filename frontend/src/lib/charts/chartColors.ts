/**
 * Chart color bridge: reads the Graphite design tokens (CSS custom properties)
 * at runtime so Highcharts options stay token-driven with zero hardcoded hex
 * values.
 *
 * Client-only: call after mount (uses `getComputedStyle`).
 */

export interface ChartColors {
  gain: string;
  loss: string;
  accent: string;
  accentMuted: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  grid: string;
  surface: string;
  /** Faint accent tint: low end of the heatmap gradient. */
  accentWash: string;
  /** Text rendered on top of accent-filled surfaces. */
  textOnAccent: string;
  /** Neutral graphite bar (primary series when not the accent). */
  bar: string;
  /** Muted comparison bar / benchmark line (grey). */
  barMute: string;
  /** Theme-aware blue (RRG credit/improving, diverging-heatmap negative, projection median). */
  blue: string;
  /** Theme-aware amber (RRG conditions/weakening). */
  amber: string;
  /** Categorical palette for multi-asset series. */
  categories: string[];
}

const CATEGORY_VARS = [
  "--color-cat-1",
  "--color-cat-2",
  "--color-cat-3",
  "--color-cat-4",
  "--color-cat-5",
  "--color-cat-6",
  "--color-cat-7",
  "--color-cat-8",
] as const;

function readVar(styles: CSSStyleDeclaration, name: string): string {
  const value = styles.getPropertyValue(name).trim();
  if (!value) {
    throw new Error(`Missing CSS custom property: ${name}`);
  }
  return value;
}

export function chartColors(): ChartColors {
  const styles = getComputedStyle(document.documentElement);
  return {
    gain: readVar(styles, "--color-gain"),
    loss: readVar(styles, "--color-loss"),
    accent: readVar(styles, "--color-accent"),
    accentMuted: readVar(styles, "--color-accent-muted"),
    accentWash: readVar(styles, "--color-accent-wash"),
    textOnAccent: readVar(styles, "--color-on-accent"),
    text: readVar(styles, "--color-text-primary"),
    textSecondary: readVar(styles, "--color-text-secondary"),
    textMuted: readVar(styles, "--color-text-muted"),
    grid: readVar(styles, "--color-chart-grid"),
    surface: readVar(styles, "--color-surface-3"),
    bar: readVar(styles, "--color-chart-bar"),
    barMute: readVar(styles, "--color-chart-bar-mute"),
    blue: readVar(styles, "--color-chart-blue"),
    amber: readVar(styles, "--color-chart-amber"),
    categories: CATEGORY_VARS.map((name) => readVar(styles, name)),
  };
}
