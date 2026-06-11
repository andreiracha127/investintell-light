/**
 * Chart color bridge — reads the Graphite design tokens (CSS custom
 * properties emitted by Tailwind's @theme in globals.css) at runtime so
 * ECharts options stay token-driven with zero hardcoded hex values.
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
}

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
    text: readVar(styles, "--color-text-primary"),
    textSecondary: readVar(styles, "--color-text-secondary"),
    textMuted: readVar(styles, "--color-text-muted"),
    grid: readVar(styles, "--color-border"),
    surface: readVar(styles, "--color-surface-3"),
  };
}
