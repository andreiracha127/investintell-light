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

function forceScaleMax(...values: number[]): number {
  const max = Math.max(...values.map((v) => Math.abs(v)), 0.1);
  return Math.min(1, Math.max(0.2, Math.ceil(max * 1.18 * 10) / 10));
}

function ForceScale({ max }: { max: number }) {
  const labels = [-max, -max / 2, 0, max / 2, max];
  return (
    <div className="mt-1 border-t border-border-strong pt-1">
      <div className="flex justify-between text-[10px] tabular-nums text-text-muted">
        {labels.map((value) => (
          <span key={value}>{formatPercent(Math.abs(value), 0)}</span>
        ))}
      </div>
    </div>
  );
}

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
  const tracked = breadth.tracked || 1;
  const advShare = breadth.advancing / tracked;
  const decShare = breadth.declining / tracked;
  const upVolumeShare = breadth.up_volume_share;
  const downVolumeShare = Math.max(0, 1 - upVolumeShare);
  const priceScaleMax = forceScaleMax(advShare, decShare);
  const volumeScaleMax = forceScaleMax(upVolumeShare, downVolumeShare);

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
          <ForceScale max={priceScaleMax} />
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
          <ForceScale max={volumeScaleMax} />
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
