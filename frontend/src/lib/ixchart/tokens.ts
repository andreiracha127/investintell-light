/**
 * Tokens do canvas lidos dos CSS custom properties do design system
 * (mesma fonte do chartColors() em src/lib/charts/theme.ts) — o chart
 * reage a tema/accent. Client-only (getComputedStyle após mount).
 * Fontes: literais (canvas não resolve var() aninhado no ctx.font).
 */
export interface IxTokens {
  bg: string;
  grid: string;
  border: string;
  borderS: string;
  text: string;
  text2: string;
  text3: string;
  graphite: string;
  pos: string;
  neg: string;
  accent: string;
  sma20: string;
  sma50: string;
  compare: string;
  mono: string;
  ui: string;
}

export function readIxTokens(): IxTokens {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string, fb: string): string => s.getPropertyValue(name).trim() || fb;
  return {
    bg: v("--color-surface-1", "#ffffff"),
    grid: v("--color-chart-grid", "#ececec"),
    border: v("--color-border", "#e0e0e0"),
    borderS: v("--color-border-strong", "#c6c6c6"),
    text: v("--color-text-primary", "#161616"),
    text2: v("--color-text-secondary", "#525252"),
    text3: v("--color-text-muted", "#6f6f6f"),
    graphite: v("--color-chart-bar", "#2b2f36"),
    pos: v("--color-gain", "#198038"),
    neg: v("--color-loss", "#a2191f"),
    accent: v("--color-accent", "#7a1c24"),
    sma20: v("--color-cat-7", "#a08184"),
    sma50: v("--color-cat-3", "#565b63"),
    compare: v("--color-cat-8", "#4d5560"),
    mono: '"Geist Mono", Consolas, ui-monospace, monospace',
    ui: 'Arial, "Arimo", sans-serif',
  };
}
