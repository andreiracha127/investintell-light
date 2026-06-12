"use client";

/** Cards SPY/QQQ/DIA/IWM: último preço (live quando o feed está aberto),
 *  variação do dia e sparkline 30d em SVG puro. */
import type { IndexCard } from "@/lib/api/client";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";

function Spark({ points }: { points: number[] }) {
  const w = 96;
  const h = 28;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const d = points
    .map((p, i) => `${((i / (points.length - 1)) * w).toFixed(1)},${(h - ((p - min) / span) * h).toFixed(1)}`)
    .join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg width={w} height={h} aria-hidden className="shrink-0">
      <polyline
        points={d}
        fill="none"
        stroke={up ? "var(--color-gain)" : "var(--color-loss)"}
        strokeWidth="1.4"
      />
    </svg>
  );
}

export function IndexStrip({ indices }: { indices: IndexCard[] }) {
  const { ticks } = useLiveTicks(indices.map((i) => i.ticker));
  if (!indices.length) return null;
  return (
    <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      {indices.map((ix) => {
        const live = ticks[ix.ticker];
        const last = live?.price ?? ix.last;
        // Baseline do live = último close do banco (ix.last) — variação de hoje.
        const chg = live && ix.last > 0 ? last / ix.last - 1 : ix.change_pct;
        const tone = chg > 0 ? "text-gain" : chg < 0 ? "text-loss" : "text-neutral-value";
        return (
          <div key={ix.ticker} className="flex items-center justify-between gap-3 bg-surface-2 px-4 py-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-text-muted">
                {ix.name} <span className="text-text-secondary">{ix.ticker}</span>
              </div>
              <div className="mt-1 flex items-baseline gap-2 tabular-nums">
                <span className="text-[18px] font-bold text-text-primary">
                  {formatCurrency(last)}
                </span>
                <span className={`text-[12px] font-bold ${tone}`}>
                  {formatPercent(chg, 2, { signed: true })}
                </span>
              </div>
            </div>
            <Spark points={ix.spark} />
          </div>
        );
      })}
    </div>
  );
}
