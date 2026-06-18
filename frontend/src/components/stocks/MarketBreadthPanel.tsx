"use client";

/** Market breadth do dia sobre o universo líquido: avançam/recuam, razão A/D,
 *  novas máximas/mínimas 52s e up-volume share. Confirma (ou desmente) a
 *  direção das tabelas de leaders. Auto-oculto se o backend não enviou breadth
 *  (pré-backfill). */
import type { MarketBreadth } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/format";
import { InfoDot, StatRow } from "@/components/ui/panels";

export function MarketBreadthPanel({ breadth }: { breadth: MarketBreadth | null }) {
  if (!breadth) return null;
  const total = breadth.tracked || 1;
  const advShare = breadth.advancing / total;
  const unchShare = breadth.unchanged / total;
  const decShare = breadth.declining / total;

  return (
    <div className="ix-pad bg-surface-2">
      <h2 className="ix-label m-0 flex items-center gap-1.5">
        Market breadth · today
        <InfoDot tip="Share of the tracked universe that is rising versus falling, with new 52-week highs/lows and the share of volume trading on up days. Broad participation confirms a move; narrow breadth warns of fragility." />
      </h2>
      <div className="mb-3 mt-0.5 text-[10px] text-text-muted">
        {formatNumber(breadth.tracked, 0)} symbols tracked
      </div>

      {/* Advancing vs declining stacked bar */}
      <div className="mb-[5px] flex items-baseline justify-between text-[12px] tabular-nums">
        <span className="font-bold text-gain">{formatNumber(breadth.advancing, 0)} advancing</span>
        <span className="font-bold text-loss">{formatNumber(breadth.declining, 0)} declining</span>
      </div>
      <div className="flex h-4 overflow-hidden border border-border">
        <div className="h-full bg-gain" style={{ width: `${advShare * 100}%` }} />
        <div className="h-full bg-[var(--ix-grey-bar)]" style={{ width: `${unchShare * 100}%` }} />
        <div className="h-full bg-loss" style={{ width: `${decShare * 100}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-text-muted">
        <span>Adv {formatPercent(advShare, 0)}</span>
        <span>Unch {formatPercent(unchShare, 0)}</span>
        <span>Dec {formatPercent(decShare, 0)}</span>
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
          <div className="flex h-2 overflow-hidden border border-border">
            <div
              className="h-full bg-gain"
              style={{ width: `${breadth.up_volume_share * 100}%` }}
            />
            <div className="h-full flex-1 bg-loss" />
          </div>
        </div>
      </dl>
    </div>
  );
}
