"use client";

/** Performance do dia por setor GICS (mediana dos constituintes líquidos),
 *  como barras divergentes a partir de uma linha-zero central.
 *  Auto-oculto enquanto o enriquecimento de setor não rodou (sectors=[]). */
import type { SectorPerf } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";
import { InfoDot } from "@/components/ui/panels";

export function SectorPanel({ sectors }: { sectors: SectorPerf[] }) {
  if (!sectors.length) return null;
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.change_pct_median)), 0.001);
  return (
    <div className="ix-pad bg-surface-2">
      <h2 className="ix-label m-0 flex items-center gap-1.5">
        Sector performance · today
        <InfoDot tip="Median daily change of each sector's liquid constituents (GICS classification). The median avoids distortion from outliers." />
      </h2>
      <div className="mb-2.5 mt-0.5 text-[10px] text-text-muted">Median of constituents</div>
      <div className="flex flex-col gap-1">
        {sectors.map((s) => {
          const pct = s.change_pct_median;
          // metade da largura disponível por lado; barra cresce a partir do centro
          const half = Math.max(1, (Math.abs(pct) / maxAbs) * 50);
          const barPos =
            pct >= 0
              ? { left: "50%", width: `${half}%` }
              : { left: `${50 - half}%`, width: `${half}%` };
          const tone = pct >= 0 ? "text-gain" : "text-loss";
          return (
            <div
              key={s.sector}
              className="grid grid-cols-[140px_1fr_56px] items-center gap-2 text-[12px]"
            >
              <span className="truncate text-text-secondary">{s.sector}</span>
              <div className="relative flex h-3.5 items-center">
                <div className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
                <div
                  className={`absolute top-0.5 h-2.5 ${pct >= 0 ? "bg-gain" : "bg-loss"}`}
                  style={barPos}
                />
              </div>
              <span className={`text-right font-bold tabular-nums ${tone}`}>
                {formatPercent(pct, 2, { signed: true })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
