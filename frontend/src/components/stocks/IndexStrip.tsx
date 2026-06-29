"use client";

/** Cards SPY/QQQ/DIA/IWM: último preço (live quando o feed está aberto),
 *  variação do dia e sparkline 30d em SVG puro. */
import { useMemo } from "react";
import type { IndexCard } from "@/lib/api/client";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";

function Spark({ points, color }: { points: number[]; color: string }) {
  const w = 96;
  const h = 30;
  // reduce-based min/max avoids argument-spread limits on large arrays.
  const { min, max } = useMemo(() => {
    let lo = points[0] ?? 0;
    let hi = lo;
    for (let i = 1; i < points.length; i++) {
      const p = points[i];
      if (p === undefined) continue;
      if (p < lo) lo = p;
      if (p > hi) hi = p;
    }
    return { min: lo, max: hi };
  }, [points]);
  const span = max - min || 1;
  const d = points
    .map((p, i) => `${((i / (points.length - 1)) * w).toFixed(1)},${(h - ((p - min) / span) * h).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={w} height={h} aria-hidden className="shrink-0">
      <polyline points={d} fill="none" stroke={color} strokeWidth="1.4" />
    </svg>
  );
}

export function IndexStrip({ indices }: { indices: IndexCard[] }) {
  // Stabilize the ticker list so useLiveTicks does not re-subscribe on every
  // render when the parent re-renders with the same indices identity.
  const tickers = useMemo(() => indices.map((i) => i.ticker), [indices]);
  const { ticks } = useLiveTicks(tickers);
  if (!indices.length) return null;
  return (
    <div className="mb-3.5 grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      {indices.map((ix) => {
        const live = ticks[ix.ticker];
        const last = live?.price ?? ix.last;
        // Baseline do live = último close do banco (ix.last) — variação de hoje.
        const chg = live && ix.last > 0 ? last / ix.last - 1 : ix.change_pct;
        const tone = chg > 0 ? "text-gain" : chg < 0 ? "text-loss" : "text-neutral-value";
        const sparkColor =
          chg > 0 ? "var(--color-gain)" : chg < 0 ? "var(--color-loss)" : "var(--color-neutral-value)";
        return (
          <div key={ix.ticker} className="ix-pad flex items-center justify-between gap-3 bg-surface-2">
            <div>
              <div className="text-[11px] font-bold text-text-secondary">
                {ix.name} <span className="font-normal text-text-muted">{ix.ticker}</span>
              </div>
              <div className="mt-px text-[10px] text-text-muted">Day change</div>
              <div className="mt-1 flex items-baseline gap-2 tabular-nums">
                <span className="text-[18px] font-bold text-text-primary">
                  {formatCurrency(last)}
                </span>
                <span className={`text-[12px] font-bold ${tone}`}>
                  {formatPercent(chg, 2, { signed: true })}
                </span>
              </div>
            </div>
            <Spark points={ix.spark} color={sparkColor} />
          </div>
        );
      })}
    </div>
  );
}
