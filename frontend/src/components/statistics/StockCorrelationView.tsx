"use client";

/**
 * Stock Correlation — pairwise correlation heatmap of a persisted
 * portfolio's holdings over a trailing window. The backend returns the
 * matrix render-ready; the heatmap builder is reused from the portfolio page.
 *
 * Design source: Statistics.dc.html — below the heatmap, a searchable,
 * sortable "Pairwise correlations" DataTable lists every unique pair with a
 * signed-strength bar. The pairs are derived from the same matrix the heatmap
 * draws; no extra request.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postStockCorrelation,
  type StockCorrelationRequest,
  type StockCorrelationResponse,
} from "@/lib/api/client";
import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatDate, formatNumber } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card } from "@/components/ui/panels";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { WindowInput, parseWindow } from "@/components/statistics/WindowInput";
import {
  ErrorPanel,
  HeatmapLegend,
  ParamsPanel,
  RunButton,
} from "@/components/statistics/ui";

export function StockCorrelationView() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [windowText, setWindowText] = useState("63");

  const mutation = useMutation({
    mutationFn: (body: StockCorrelationRequest) => postStockCorrelation(body),
  });

  const window = parseWindow(windowText);
  const canRun = portfolioId !== null && window !== null;
  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    mutation.mutate({ portfolio_id: portfolioId, window });
  };

  return (
    <StatisticsShell>
      <ParamsPanel>
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} />
        <WindowInput value={windowText} onChange={setWindowText} />
        <RunButton
          pending={mutation.isPending}
          disabled={!canRun}
          onClick={onRun}
        />
      </ParamsPanel>

      {mutation.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading stock correlation"
          className="h-[480px] animate-pulse bg-surface-2"
        />
      ) : mutation.isError ? (
        <ErrorPanel
          title="Stock correlation failed"
          message={mutation.error.message}
        />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="ix-pad ix-fs border border-border bg-surface-2 text-text-muted">
          Pick a portfolio and a trailing window, then press Run to compute the
          pairwise correlation of its holdings.
        </p>
      )}
    </StatisticsShell>
  );
}

/* ── Results ──────────────────────────────────────────────────────────────── */

function Results({
  data,
  colors,
}: {
  data: StockCorrelationResponse;
  colors: ChartColors;
}) {
  const heatmapOption = useMemo(
    () =>
      buildHcHeatmapOption(data, colors, {
        diverging: true,
        negativeColor: colors.loss,
        zeroColor: colors.surface,
      }),
    [data, colors],
  );

  return (
    <div className="flex flex-col gap-px">
      <Card
        title="Correlation Matrix"
        subtitle={`as of ${formatDate(data.as_of)} · ${formatNumber(data.window, 0)}d window`}
        actions={<HeatmapLegend />}
      >
        <HighchartsChart options={heatmapOption} className="h-[440px] w-full" />
      </Card>
      <PairsTable tickers={data.tickers} matrix={data.matrix} />
    </div>
  );
}

/* ── Pairwise correlations DataTable ─────────────────────────────────────────
 * Derived from the same symmetric matrix the heatmap draws: every unique
 * (a < b) pair, filterable by ticker and sortable on each column. The signed
 * "strength" bar reuses the accent (positive) / loss (negative) tones. */

type Pair = { a: string; b: string; corr: number };
type SortKey = "a" | "b" | "corr" | "abscorr";
type SortDir = "asc" | "desc";

function strengthLabel(r: number): string {
  const a = Math.abs(r);
  if (a >= 0.8) return "Very strong";
  if (a >= 0.6) return "Strong";
  if (a >= 0.4) return "Moderate";
  if (a >= 0.2) return "Weak";
  return "Very weak";
}

function PairsTable({
  tickers,
  matrix,
}: {
  tickers: string[];
  matrix: number[][];
}) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("abscorr");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const allPairs = useMemo<Pair[]>(() => {
    const out: Pair[] = [];
    for (let a = 0; a < tickers.length; a++) {
      for (let b = a + 1; b < tickers.length; b++) {
        out.push({ a: tickers[a], b: tickers[b], corr: matrix[a][b] });
      }
    }
    return out;
  }, [tickers, matrix]);

  const pairs = useMemo<Pair[]>(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? allPairs.filter(
          (p) => p.a.toLowerCase().includes(q) || p.b.toLowerCase().includes(q),
        )
      : allPairs.slice();
    const dir = sortDir === "asc" ? 1 : -1;
    filtered.sort((x, y) => {
      if (sortKey === "a") return x.a < y.a ? -dir : x.a > y.a ? dir : 0;
      if (sortKey === "b") return x.b < y.b ? -dir : x.b > y.b ? dir : 0;
      if (sortKey === "corr") return (x.corr - y.corr) * dir;
      return (Math.abs(x.corr) - Math.abs(y.corr)) * dir;
    });
    return filtered;
  }, [allPairs, search, sortKey, sortDir]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const HEADERS: ReadonlyArray<{ key: SortKey; label: string; align: "left" | "right" }> = [
    { key: "a", label: "Asset A", align: "left" },
    { key: "b", label: "Asset B", align: "left" },
    { key: "corr", label: "Correlation", align: "right" },
    { key: "abscorr", label: "Strength", align: "right" },
  ];

  return (
    <section className="border border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <h2 className="m-0 text-[13px] font-bold text-text-primary">
          Pairwise correlations
        </h2>
        <div className="flex h-8 items-center gap-2 border border-border-strong bg-field px-2.5">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" className="text-text-muted" />
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.4" className="text-text-muted" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by ticker…"
            aria-label="Filter pairs"
            className="w-[150px] border-0 bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-muted"
          />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse">
          <thead>
            <tr>
              {HEADERS.map((h) => {
                const active = h.key === sortKey;
                const arrow = active ? (sortDir === "asc" ? "▲" : "▼") : "";
                return (
                  <th
                    key={h.key}
                    scope="col"
                    aria-sort={
                      active
                        ? sortDir === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                    onClick={() => onSort(h.key)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSort(h.key);
                      }
                    }}
                    tabIndex={0}
                    className={`cursor-pointer whitespace-nowrap bg-surface-2 px-3 py-2.5 text-[10.5px] font-bold uppercase tracking-[0.06em] text-text-muted ${
                      h.align === "right" ? "text-right" : "text-left"
                    }`}
                  >
                    {h.label}
                    {arrow && <span className="ml-1 text-accent">{arrow}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pairs.map((p, i) => {
              const positive = p.corr >= 0;
              const barTone = positive ? "bg-accent" : "bg-loss";
              const textTone = positive ? "text-accent" : "text-loss";
              return (
                <tr
                  key={`${p.a}-${p.b}`}
                  className={i % 2 ? "bg-zebra" : "bg-surface-2"}
                >
                  <td className="px-3 py-2 text-[12.5px] font-bold text-text-secondary">
                    {p.a}
                  </td>
                  <td className="px-3 py-2 text-[12.5px] font-bold text-text-secondary">
                    {p.b}
                  </td>
                  <td className={`px-3 py-2 text-right text-[12.5px] font-bold tabular-nums ${textTone}`}>
                    {formatNumber(p.corr, 3)}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex items-center justify-end gap-2">
                      <span className="relative h-[6px] w-[90px] bg-layer-active">
                        <span
                          className={`absolute left-0 top-0 h-[6px] ${barTone}`}
                          style={{ width: `${(Math.abs(p.corr) * 100).toFixed(0)}%` }}
                        />
                      </span>
                      <span className="w-[64px] text-[10.5px] text-text-muted">
                        {strengthLabel(p.corr)}
                      </span>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {pairs.length === 0 && (
        <div className="px-[var(--ix-pad)] py-7 text-center text-[12.5px] text-text-muted">
          No pairs match “{search}”.
        </div>
      )}
    </section>
  );
}
