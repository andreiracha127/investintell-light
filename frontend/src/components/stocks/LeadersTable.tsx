"use client";

/**
 * Market Leaders com tabs (Most Active / Gainers / Losers / 52w High / 52w
 * Low). Last/Chg atualizam ao vivo (flash gain/loss); o RANKING não re-sorta
 * por tick — ordem fixa até o refetch (evita a tabela "pulando").
 * Clique na linha → /stocks/{ticker}; botão "+" → AddToPortfolio.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { LeaderRow, MarketOverview } from "@/lib/api/client";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { AddToPortfolio } from "@/components/stocks/AddToPortfolio";

const TABS = [
  { key: "most_active", label: "Most Active" },
  { key: "gainers", label: "Gainers" },
  { key: "losers", label: "Losers" },
  { key: "highs_52w", label: "52w Highs" },
  { key: "lows_52w", label: "52w Lows" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function LeadersTable({ overview }: { overview: MarketOverview }) {
  const router = useRouter();
  const [tab, setTab] = useState<TabKey>("most_active");
  const rows: LeaderRow[] = overview[tab];
  const { ticks } = useLiveTicks(rows.map((r) => r.ticker));

  return (
    <div className="border border-border bg-surface-2">
      <div role="tablist" aria-label="Market leaders" className="flex border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-3.5 py-2 text-[12px] transition-colors ${
              tab === t.key
                ? "font-bold text-accent shadow-[inset_0_-2px_0_var(--color-accent)]"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <table className="w-full border-collapse text-[12.5px] tabular-nums">
        <thead>
          <tr className="text-left text-[10.5px] uppercase tracking-[0.08em] text-text-muted">
            <th className="px-3 py-2 font-bold">Symbol</th>
            <th className="px-3 py-2 font-bold">Name</th>
            <th className="px-3 py-2 text-right font-bold">Last</th>
            <th className="px-3 py-2 text-right font-bold">Chg</th>
            <th className="px-3 py-2 text-right font-bold">%Chg</th>
            <th className="hidden px-3 py-2 text-right font-bold md:table-cell">Volume</th>
            <th className="hidden px-3 py-2 text-right font-bold lg:table-cell">52w Range</th>
            <th className="px-3 py-2" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const live = ticks[r.ticker];
            const last = live?.price ?? r.last;
            // Baseline do live = último close do banco (r.last): durante o
            // pregão o banco ainda tem o close de ontem, então live/r.last - 1
            // é a variação de HOJE. Sem tick, vale o EOD do payload.
            const change = live ? last - r.last : r.change;
            const changePct = live && r.last > 0 ? last / r.last - 1 : r.change_pct;
            const tone = change > 0 ? "text-gain" : change < 0 ? "text-loss" : "text-neutral-value";
            const flash =
              live?.dir === 1 ? "animate-pulse text-gain" : live?.dir === -1 ? "animate-pulse text-loss" : "";
            return (
              <tr
                key={r.ticker}
                onClick={() => router.push(`/stocks/${encodeURIComponent(r.ticker)}`)}
                className="cursor-pointer border-t border-border hover:bg-layer-hover"
              >
                <td className="px-3 py-1.5 font-bold text-accent">{r.ticker}</td>
                <td className="max-w-[260px] truncate px-3 py-1.5 text-text-secondary">{r.name}</td>
                <td className={`px-3 py-1.5 text-right font-bold text-text-primary ${flash}`}>
                  {formatCurrency(last)}
                </td>
                <td className={`px-3 py-1.5 text-right ${tone}`}>
                  {formatCurrency(change, { signed: true })}
                </td>
                <td className={`px-3 py-1.5 text-right font-bold ${tone}`}>
                  {formatPercent(changePct, 2, { signed: true })}
                </td>
                <td className="hidden px-3 py-1.5 text-right text-text-secondary md:table-cell">
                  {formatNumber(r.volume, 0)}
                </td>
                <td className="hidden px-3 py-1.5 text-right text-text-muted lg:table-cell">
                  {formatCurrency(r.low_52w)} – {formatCurrency(r.high_52w)}
                </td>
                <td className="px-3 py-1.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <AddToPortfolio ticker={r.ticker} />
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="px-3 py-6 text-center text-[12px] text-text-muted">
                No data — universe EOD backfill has not run yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
