/**
 * Funções puras do chart interativo: resample D/W/M, indicadores e
 * formatadores. Port de design/assets/chart-engine.js (repo workers),
 * sem dados sintéticos — barras reais vêm de GET /stocks/{ticker}/history.
 */
import type { Bar, Period } from "./types";

export function resample(bars: Bar[], period: Period): Bar[] {
  if (period === "D") return bars;
  const keyOf = (t: number): number => {
    const d = new Date(t);
    if (period === "M") return d.getFullYear() * 100 + d.getMonth();
    // semana ISO aproximada: ano*100 + nº da semana
    const onejan = new Date(d.getFullYear(), 0, 1);
    return (
      d.getFullYear() * 100 +
      Math.floor((((t - onejan.getTime()) / 86_400_000) + onejan.getDay()) / 7)
    );
  };
  const out: Bar[] = [];
  let cur: Bar | null = null;
  let curKey: number | null = null;
  for (const b of bars) {
    const k = keyOf(b.t);
    if (k !== curKey) {
      if (cur) out.push(cur);
      curKey = k;
      cur = { ...b };
    } else if (cur) {
      cur.h = Math.max(cur.h, b.h);
      cur.l = Math.min(cur.l, b.l);
      cur.c = b.c;
      cur.v += b.v;
    }
  }
  if (cur) out.push(cur);
  return out;
}

export function sma(bars: Bar[], p: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let acc = 0;
  for (let i = 0; i < bars.length; i++) {
    acc += bars[i].c;
    if (i >= p) acc -= bars[i - p].c;
    if (i >= p - 1) out[i] = acc / p;
  }
  return out;
}

export function rsi(bars: Bar[], p = 14): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let g = 0;
  let l = 0;
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i].c - bars[i - 1].c;
    const up = Math.max(d, 0);
    const dn = Math.max(-d, 0);
    if (i <= p) {
      g += up / p;
      l += dn / p;
    } else {
      g = (g * (p - 1) + up) / p;
      l = (l * (p - 1) + dn) / p;
    }
    if (i >= p) out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}

export function niceTicks(min: number, max: number, target: number): number[] {
  const span = max - min;
  if (!(span > 0)) return [];
  const raw = span / Math.max(2, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= target + 1) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

export const fmtP = (x: number | null | undefined, dec: number): string =>
  x == null
    ? "—"
    : x.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

export const fmtV = (x: number): string =>
  x >= 1e9 ? (x / 1e9).toFixed(2) + "B"
  : x >= 1e6 ? (x / 1e6).toFixed(2) + "M"
  : x >= 1e3 ? (x / 1e3).toFixed(1) + "K"
  : String(Math.round(x));

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const fmtD = (t: number): string => {
  const d = new Date(t);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
};

export { MONTHS };
