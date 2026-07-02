"use client";

/** Performance do dia por setor GICS (mediana dos constituintes líquidos),
 *  como barras divergentes a partir de uma linha-zero central.
 *  Auto-oculto enquanto o enriquecimento de setor não rodou (sectors=[]). */
import type { SectorPerf } from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { buildHcSectorPerformanceOption } from "@/lib/charts/hc/stock-overview";
import { InfoDot } from "@/components/ui/panels";
import { useEffect, useMemo, useState } from "react";

export function SectorPanel({ sectors }: { sectors: SectorPerf[] }) {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => setColors(chartColors()), []);

  const option = useMemo(
    () => (colors ? buildHcSectorPerformanceOption(sectors, colors) : null),
    [colors, sectors],
  );

  if (!sectors.length) return null;
  return (
    <div className="ix-pad bg-surface-2">
      <h2 className="ix-label m-0 flex items-center gap-1.5">
        Sector performance · today
        <InfoDot tip="Median daily change of each sector's liquid constituents (GICS classification). The median avoids distortion from outliers." />
      </h2>
      <div className="mb-2.5 mt-0.5 text-[10px] text-text-muted">Price force by sector · median of constituents</div>
      {option ? (
        <HighchartsChart options={option} className="h-[316px] w-full" />
      ) : (
        <div className="flex h-[316px] items-center justify-center bg-field text-[12px] text-text-muted">
          Preparing sector chart...
        </div>
      )}
    </div>
  );
}
