"use client";

/** Market breadth do dia sobre o universo líquido: avançam/recuam, razão A/D,
 *  novas máximas/mínimas 52s e up-volume share. Confirma (ou desmente) a
 *  direção das tabelas de leaders. Auto-oculto se o backend não enviou breadth
 *  (pré-backfill). */
import type { MarketBreadth } from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  buildHcMarketBreadthOption,
  buildHcVolumeBreadthOption,
} from "@/lib/charts/hc/stock-overview";
import { formatNumber, formatPercent } from "@/lib/format";
import { InfoDot, StatRow } from "@/components/ui/panels";
import { useEffect, useMemo, useState } from "react";

export function MarketBreadthPanel({ breadth }: { breadth: MarketBreadth | null }) {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => setColors(chartColors()), []);

  const priceOption = useMemo(
    () => (breadth && colors ? buildHcMarketBreadthOption(breadth, colors) : null),
    [breadth, colors],
  );
  const volumeOption = useMemo(
    () => (breadth && colors ? buildHcVolumeBreadthOption(breadth, colors) : null),
    [breadth, colors],
  );
  if (!breadth) return null;

  return (
    <div className="ix-pad bg-surface-2">
      <h2 className="ix-label m-0 flex items-center gap-1.5">
        Market breadth · today
        <InfoDot tip="Share of the tracked universe that is rising versus falling, with new 52-week highs/lows and the share of volume trading on up days. Broad participation confirms a move; narrow breadth warns of fragility." />
      </h2>
      <div className="mb-3 mt-0.5 text-[10px] text-text-muted">
        {formatNumber(breadth.tracked, 0)} stocks tracked
      </div>

      <div className="mb-2 flex items-baseline justify-between text-[12px] tabular-nums">
        <span className="font-bold text-loss">{formatNumber(breadth.declining, 0)} declining</span>
        <span className="font-bold text-gain">{formatNumber(breadth.advancing, 0)} advancing</span>
      </div>
      <div className="space-y-2">
        <div>
          <div className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
            <span>Price breadth</span>
            <span>Stocks</span>
          </div>
          {priceOption ? (
            <HighchartsChart options={priceOption} className="h-[70px] w-full" />
          ) : (
            <div className="flex h-[70px] items-center justify-center bg-field text-[12px] text-text-muted">
              Preparing price breadth...
            </div>
          )}
        </div>
        <div>
          <div className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
            <span>Volume breadth</span>
            <span>Traded volume</span>
          </div>
          {volumeOption ? (
            <HighchartsChart options={volumeOption} className="h-[70px] w-full" />
          ) : (
            <div className="flex h-[70px] items-center justify-center bg-field text-[12px] text-text-muted">
              Preparing volume breadth...
            </div>
          )}
        </div>
      </div>
      <dl className="mt-4">
        <StatRow
          label="Advance / decline ratio"
          value={formatNumber(breadth.advance_decline_ratio, 2)}
        />
        <StatRow
          label="New 52-week highs"
          value={formatNumber(breadth.new_highs_52w, 0)}
          tone="text-gain"
        />
        <StatRow
          label="New 52-week lows"
          value={formatNumber(breadth.new_lows_52w, 0)}
          tone="text-loss"
        />
        <div className="ix-cell">
          <div className="mb-[5px] flex items-baseline justify-between text-[12px]">
            <dt className="flex items-center gap-1.5 text-text-secondary">
              Up-volume share
              <InfoDot tip="Percentage of total traded volume occurring in advancing stocks. Above 50% signals buying pressure." />
            </dt>
            <dd className="m-0 font-bold tabular-nums text-gain">
              {formatPercent(breadth.up_volume_share, 0)}
            </dd>
          </div>
        </div>
      </dl>
    </div>
  );
}
