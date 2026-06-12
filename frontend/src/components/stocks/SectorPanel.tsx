"use client";

/** Performance do dia por setor GICS (mediana dos constituintes líquidos).
 *  Auto-oculto enquanto o enriquecimento de setor não rodou (sectors=[]). */
import type { SectorPerf } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

export function SectorPanel({ sectors }: { sectors: SectorPerf[] }) {
  if (!sectors.length) return null;
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.change_pct_median)), 0.001);
  return (
    <div className="border border-border bg-surface-2 px-4 py-3">
      <h2 className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-muted">
        Sectors · today (median)
      </h2>
      <div className="flex flex-col gap-1">
        {sectors.map((s) => {
          const pct = s.change_pct_median;
          const width = Math.max(2, (Math.abs(pct) / maxAbs) * 100);
          return (
            <div key={s.sector} className="grid grid-cols-[170px_1fr_64px] items-center gap-2 text-[12px]">
              <span className="truncate text-text-secondary">{s.sector}</span>
              <div className="flex h-3 items-center">
                <div
                  className={pct >= 0 ? "bg-gain" : "bg-loss"}
                  style={{ width: `${width}%`, height: "10px" }}
                />
              </div>
              <span className={`text-right font-bold tabular-nums ${pct >= 0 ? "text-gain" : "text-loss"}`}>
                {formatPercent(pct, 2, { signed: true })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
