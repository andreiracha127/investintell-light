"use client";

/**
 * Market Leaders com tabs (Most Active / Gainers / Losers / 52w High / 52w
 * Low), busca, ordenação por coluna, zebra striping e paginação "load more".
 *
 * Last/Chg atualizam ao vivo (flash gain/loss); o RANKING não re-sorta por
 * tick — a ordem usa os valores do payload (r.last/r.change…), então a tabela
 * não "pula" a cada cotação. Clique na linha → /stocks/{ticker}; "+" abre o
 * AddToPortfolio.
 */
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
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

type SortKey = "ticker" | "name" | "last" | "change" | "change_pct" | "volume";

const COLUMNS: {
  key: SortKey | "range" | "actions";
  label: string;
  align: "left" | "right";
  sortable: boolean;
  cls?: string;
}[] = [
  { key: "ticker", label: "Symbol", align: "left", sortable: true },
  { key: "name", label: "Name", align: "left", sortable: true },
  { key: "last", label: "Last", align: "right", sortable: true },
  { key: "change", label: "Chg", align: "right", sortable: true },
  { key: "change_pct", label: "%Chg", align: "right", sortable: true },
  { key: "volume", label: "Volume", align: "right", sortable: true, cls: "hidden md:table-cell" },
  { key: "range", label: "52w Range", align: "right", sortable: false, cls: "hidden lg:table-cell" },
  { key: "actions", label: "", align: "right", sortable: false },
];

const NUMERIC_KEYS = new Set<SortKey>(["last", "change", "change_pct", "volume"]);
const PAGE = 12;

function compareRows(a: LeaderRow, b: LeaderRow, key: SortKey, dir: "asc" | "desc"): number {
  let result: number;
  if (key === "ticker") result = a.ticker.localeCompare(b.ticker);
  else if (key === "name") result = (a.name ?? "").localeCompare(b.name ?? "");
  else result = a[key] - b[key];
  return dir === "asc" ? result : -result;
}

export function LeadersTable({ overview }: { overview: MarketOverview }) {
  const router = useRouter();
  const [tab, setTab] = useState<TabKey>("most_active");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [visible, setVisible] = useState(PAGE);

  const rows: LeaderRow[] = overview[tab];

  const processed = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (r) =>
            r.ticker.toLowerCase().includes(q) ||
            (r.name ?? "").toLowerCase().includes(q),
        )
      : rows;
    return sortKey
      ? [...filtered].sort((a, b) => compareRows(a, b, sortKey, sortDir))
      : filtered;
  }, [rows, search, sortKey, sortDir]);

  const shown = processed.slice(0, visible);
  const remaining = processed.length - shown.length;
  const searchMiss = processed.length === 0 && search.trim().length > 0;
  const { ticks } = useLiveTicks(shown.map((r) => r.ticker));

  function selectTab(next: TabKey) {
    setTab(next);
    setSortKey(null);
    setVisible(PAGE);
  }

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(NUMERIC_KEYS.has(key) ? "desc" : "asc");
    }
  }

  return (
    <div className="mb-3.5 border border-border bg-surface-2">
      {/* Card header: title + search */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[14px] py-3">
        <h2 className="m-0 text-[13px] font-bold text-text-primary">Market leaders</h2>
        <div className="flex h-8 min-w-[230px] items-center gap-2 border border-border-strong bg-field px-2.5">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden className="text-text-muted">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setVisible(PAGE);
            }}
            placeholder="Search symbol or company"
            aria-label="Search table"
            className="flex-1 border-none bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-muted"
          />
        </div>
      </div>

      {/* Category tabs */}
      <div role="tablist" aria-label="Market leaders" className="flex flex-wrap border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            type="button"
            onClick={() => selectTab(t.key)}
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

      {searchMiss ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-text-muted">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
            <path d="M16 16l5 5" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          <div className="text-[13px] text-text-secondary">No results for “{search.trim()}”.</div>
          <button
            type="button"
            onClick={() => setSearch("")}
            className="mt-1 border border-border-strong bg-field px-3.5 py-1.5 text-[12px] font-semibold text-text-primary hover:bg-layer-hover transition-colors"
          >
            Clear search
          </button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[12.5px] tabular-nums">
              <thead>
                <tr>
                  {COLUMNS.map((col) => {
                    const active = col.key === sortKey;
                    const arrow = active ? (sortDir === "asc" ? "↑" : "↓") : "";
                    return (
                      <th
                        key={col.key}
                        scope="col"
                        aria-sort={
                          active ? (sortDir === "asc" ? "ascending" : "descending") : "none"
                        }
                        aria-label={col.key === "actions" ? "Actions" : undefined}
                        tabIndex={col.sortable ? 0 : undefined}
                        onClick={col.sortable ? () => handleSort(col.key as SortKey) : undefined}
                        onKeyDown={
                          col.sortable
                            ? (e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  handleSort(col.key as SortKey);
                                }
                              }
                            : undefined
                        }
                        className={`px-3 py-2 text-[10.5px] font-bold uppercase tracking-[0.08em] text-text-muted ${
                          col.align === "right" ? "text-right" : "text-left"
                        } ${col.sortable ? "cursor-pointer select-none hover:text-text-primary" : ""} ${col.cls ?? ""}`}
                      >
                        <span
                          className={`inline-flex items-center gap-1 ${
                            col.align === "right" ? "justify-end" : ""
                          }`}
                        >
                          {col.label}
                          {arrow && <span className="text-[9px] text-accent">{arrow}</span>}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
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
                      className={`cursor-pointer border-t border-border hover:bg-layer-hover ${
                        i % 2 === 1 ? "bg-zebra" : ""
                      }`}
                    >
                      <td className="px-3 py-1.5 font-bold text-accent">{r.ticker}</td>
                      <td className="max-w-[240px] truncate px-3 py-1.5 text-text-secondary">{r.name}</td>
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
                      <td className="hidden whitespace-nowrap px-3 py-1.5 text-right text-text-muted lg:table-cell">
                        {formatCurrency(r.low_52w)} – {formatCurrency(r.high_52w)}
                      </td>
                      <td className="px-2 py-1.5 text-right" onClick={(e) => e.stopPropagation()}>
                        <AddToPortfolio ticker={r.ticker} price={last} />
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[12px] text-text-muted">
                      No data — universe EOD backfill has not run yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {remaining > 0 && (
            <div className="flex justify-center border-t border-border p-2.5">
              <button
                type="button"
                onClick={() => setVisible((v) => v + PAGE)}
                className="border border-border-strong bg-field px-[18px] py-[7px] text-[12px] font-semibold text-text-primary hover:bg-layer-hover transition-colors"
              >
                Load more ({remaining})
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
