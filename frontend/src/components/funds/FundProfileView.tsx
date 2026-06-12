"use client";

/**
 * Fund profile (F8.2) — GET /funds/{id}: serif header with tags, KPI tiles,
 * 2y NAV chart (decimated server-side), top holdings (top-50-truncated
 * N-PORT source, disclaimed) and the full precomputed risk-metric panel.
 * Every number is the mother-DB value with its source calc_date.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { fetchFundProfile, type FundRisk } from "@/lib/api/client";
import { EChart } from "@/components/charts/EChart";
import { FundLookthroughSection } from "@/components/funds/FundLookthroughSection";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card, KpiTile, StatRow } from "@/components/ui/panels";
import { buildFundNavOption } from "@/lib/charts/fundnav";
import {
  buildDrawdownOption,
  buildMonthlyReturnsOption,
} from "@/lib/charts/performance";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import {
  formatCompact,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { drawdownSeries, monthlyReturns } from "@/lib/perf";

const TYPE_TAG: Record<string, string> = {
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "Money market",
};

// The Sector column shows the REAL GICS sector (holding.gics_sector, mapped
// in the data-lake via sec_cusip_ticker_map). For government/municipal/fund
// paper — where GICS does not apply — the N-PORT issuerCat gives the
// fixed-income sector. Unmapped issuers show "—", never a raw code.
const NPORT_ISSUER_SECTOR: Record<string, string> = {
  UST: "Government",
  USGA: "Agency",
  USGSE: "GSE",
  MUN: "Municipal",
  NUSS: "Sovereign",
  RF: "Fund",
  PF: "Private fund",
};

function holdingSectorLabel(
  gicsSector: string | null,
  issuerCat: string | null,
): string | null {
  return gicsSector ?? NPORT_ISSUER_SECTOR[issuerCat ?? ""] ?? null;
}

function pct(value: number | null | undefined, dp = 2): string {
  return value !== null && value !== undefined ? formatPercent(value, dp) : "—";
}

function num(value: number | null | undefined, dp = 2): string {
  return value !== null && value !== undefined ? formatNumber(value, dp) : "—";
}

export function FundProfileView({ instrumentId }: { instrumentId: string }) {
  const profileQuery = useQuery({
    queryKey: ["fund-profile", instrumentId],
    queryFn: ({ signal }) => fetchFundProfile(instrumentId, signal),
    staleTime: 30_000,
    retry: retryPolicy,
  });

  // chartColors() reads CSS custom properties — client-only, after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const navOption = useMemo(
    () =>
      profileQuery.data && colors
        ? buildFundNavOption(profileQuery.data.nav, colors)
        : null,
    [profileQuery.data, colors],
  );

  // Monthly returns heatmap — only shown when the nav spans ≥ 13 months
  // (the first month is always excluded as a baseline; ≥13 months guarantees
  // at least one full-month return to display).
  const monthlyReturnsOption = useMemo(() => {
    if (!profileQuery.data || !colors) return null;
    const nav = profileQuery.data.nav;
    // Check span: compare first and last valid-date's year×month.
    const dates = nav
      .filter((p) => p.nav !== null)
      .map((p) => p.date)
      .sort();
    if (dates.length < 2) return null;
    const [fy, fm] = dates[0].split("-").map(Number);
    const [ly, lm] = dates[dates.length - 1].split("-").map(Number);
    const spanMonths = (ly - fy) * 12 + (lm - fm);
    if (spanMonths < 13) return null;
    const cells = monthlyReturns(nav);
    return buildMonthlyReturnsOption(cells, colors);
  }, [profileQuery.data, colors]);

  // Drawdown chart — only shown when nav spans ≥ 13 months (same gate).
  const drawdownOption = useMemo(() => {
    if (!profileQuery.data || !colors) return null;
    const nav = profileQuery.data.nav;
    const dates = nav
      .filter((p) => p.nav !== null)
      .map((p) => p.date)
      .sort();
    if (dates.length < 2) return null;
    const [fy, fm] = dates[0].split("-").map(Number);
    const [ly, lm] = dates[dates.length - 1].split("-").map(Number);
    const spanMonths = (ly - fy) * 12 + (lm - fm);
    if (spanMonths < 13) return null;
    const dd = drawdownSeries(nav);
    return buildDrawdownOption(dd, colors);
  }, [profileQuery.data, colors]);

  if (profileQuery.isPending) {
    return (
      <div className="mx-auto max-w-[1400px] px-5 py-5">
        <div
          aria-busy="true"
          aria-label="Loading fund profile"
          className="h-[480px] bg-surface-2 animate-pulse"
        />
      </div>
    );
  }
  if (profileQuery.isError) {
    return (
      <div className="mx-auto max-w-[1400px] px-5 py-5">
        <ErrorPanel
          title="Failed to load fund"
          message={profileQuery.error.message}
          onRetry={() => profileQuery.refetch()}
        />
      </div>
    );
  }

  const fund = profileQuery.data;
  const risk = fund.risk;

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="mb-4">
        <Link
          href="/funds"
          className="text-[11px] font-bold uppercase tracking-[0.08em] text-text-muted hover:text-accent"
        >
          ← Funds
        </Link>
        <div className="mt-1 flex flex-wrap items-baseline gap-3">
          <h1 className="ix-title m-0 text-[clamp(22px,3.5vw,28px)]">{fund.name}</h1>
          {fund.ticker && (
            <span className="text-[15px] font-bold tabular-nums text-accent">
              {fund.ticker}
            </span>
          )}
        </div>
        <div className="mb-1.5 mt-2 h-[3px] w-[34px] bg-accent" />
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Tag>{TYPE_TAG[fund.fund_type] ?? fund.fund_type}</Tag>
          <Tag>{fund.strategy_label}</Tag>
          {fund.asset_class && <Tag>{fund.asset_class.replace("_", " ")}</Tag>}
          {fund.is_index && <Tag>Index</Tag>}
        </div>
        <p className="mt-2 text-[12px] text-text-secondary">
          Data as of {formatDate(fund.source_calc_date)} · NAV through{" "}
          {formatDate(fund.source_nav_max_date)}
          {fund.primary_benchmark ? ` · Benchmark: ${fund.primary_benchmark}` : ""}
        </p>
      </div>

      {/* ── KPI tiles ───────────────────────────────────────────────────── */}
      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="AUM"
          value={fund.aum_usd !== null ? `$${formatCompact(fund.aum_usd)}` : "—"}
        />
        <KpiTile label="Expense" value={pct(fund.expense_ratio)} />
        <KpiTile
          label="Return 1Y"
          value={
            risk?.return_1y !== null && risk?.return_1y !== undefined
              ? formatPercent(risk.return_1y, 2, { signed: true })
              : "—"
          }
          tone={
            risk?.return_1y !== null && risk?.return_1y !== undefined
              ? risk.return_1y > 0
                ? "text-gain"
                : risk.return_1y < 0
                  ? "text-loss"
                  : "text-text-primary"
              : "text-text-primary"
          }
        />
        <KpiTile label="Vol 1Y" value={pct(risk?.volatility_1y)} />
        <KpiTile label="Sharpe 1Y" value={num(risk?.sharpe_1y)} />
        <KpiTile label="CVaR 95 12M" value={pct(risk?.cvar_95_12m)} />
      </div>

      {/* ── NAV chart + risk metrics ────────────────────────────────────── */}
      <div className="grid gap-4 lg:[grid-template-columns:2fr_1fr]">
        <div className="flex flex-col gap-4">
          <Card title="NAV" subtitle="2y window, decimated server-side">
            {fund.nav.length > 0 && navOption ? (
              <EChart option={navOption} className="h-[300px] w-full" />
            ) : (
              <p className="py-8 text-center text-[13px] text-text-muted">
                No NAV history in the synced window.
              </p>
            )}
          </Card>

          {monthlyReturnsOption && (
            <Card title="Monthly returns" subtitle="month-end over month-end, 2y window">
              <EChart option={monthlyReturnsOption} className="h-[220px] w-full" />
            </Card>
          )}

          {drawdownOption && (
            <Card title="Drawdown" subtitle="running peak-to-trough, 2y window">
              <EChart option={drawdownOption} className="h-[180px] w-full" />
            </Card>
          )}

          <Card
            title="Top holdings"
            subtitle={
              fund.holdings.report_date
                ? `N-PORT, report ${formatDate(fund.holdings.report_date)}`
                : undefined
            }
          >
            {fund.holdings.items.length > 0 ? (
              <>
                <table className="w-full border-collapse ix-fs tabular-nums lining-nums">
                  <thead>
                    <tr className="bg-field">
                      <th className="px-2.5 py-[7px] text-left text-[11px] font-semibold text-text-secondary border-b border-border-strong w-10">
                        #
                      </th>
                      <th className="px-2.5 py-[7px] text-left text-[11px] font-semibold text-text-secondary border-b border-border-strong">
                        Issuer
                      </th>
                      <th className="px-2.5 py-[7px] text-left text-[11px] font-semibold text-text-secondary border-b border-border-strong">
                        Sector
                      </th>
                      <th className="px-2.5 py-[7px] text-right text-[11px] font-semibold text-text-secondary border-b border-border-strong">
                        % NAV
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {fund.holdings.items.map((holding, i) => (
                      <tr
                        key={holding.rank}
                        className={`border-b border-border transition-colors hover:bg-accent-wash ${
                          i % 2 === 1 ? "bg-zebra" : ""
                        }`}
                      >
                        <td className="ix-cell px-2.5 text-text-muted">{holding.rank}</td>
                        <td className="ix-cell px-2.5 text-left">
                          <span className="block max-w-[320px] truncate">
                            {holding.issuer_name ?? "—"}
                          </span>
                        </td>
                        <td className="ix-cell px-2.5 text-left text-text-secondary">
                          <span className="block max-w-[200px] truncate">
                            {holdingSectorLabel(
                              holding.gics_sector,
                              holding.sector,
                            ) ?? "—"}
                          </span>
                        </td>
                        {/* N-PORT pct_of_nav is already in percent units
                            (11.62 = 11.62%) — unlike the risk fractions. */}
                        <td className="ix-cell px-2.5 text-right">
                          {holding.pct_of_nav !== null
                            ? `${formatNumber(holding.pct_of_nav)}%`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {/* The top-50 truncation gate was retired (Frente C): the
                    backend no longer exposes is_top50_truncated. */}
                <p className="mt-2 text-[11px] text-text-muted">
                  {fund.holdings.pct_of_nav_total !== null &&
                    `Reported holdings sum to ${formatNumber(
                      fund.holdings.pct_of_nav_total,
                      1,
                    )}% of NAV`}
                </p>
              </>
            ) : (
              <p className="py-8 text-center text-[13px] text-text-muted">
                No N-PORT holdings synced for this fund&apos;s series.
              </p>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card
            title="Risk metrics"
            subtitle={risk ? `calc ${formatDate(risk.calc_date)}` : undefined}
          >
            {risk ? (
              <dl className="m-0">
                <RiskRows risk={risk} />
              </dl>
            ) : (
              <p className="py-8 text-center text-[13px] text-text-muted">
                No risk snapshot synced for this fund.
              </p>
            )}
          </Card>

          <Card title="Identity">
            <dl className="m-0">
              <StatRow label="Series" value={fund.series_id} />
              <StatRow label="ISIN" value={fund.isin ?? "—"} />
              <StatRow label="CUSIP" value={fund.cusip ?? "—"} />
              <StatRow
                label="Inception"
                value={fund.inception_date ? formatDate(fund.inception_date) : "—"}
              />
              <StatRow label="Domicile" value={fund.domicile ?? "—"} />
              <StatRow label="Currency" value={fund.currency ?? "—"} />
            </dl>
          </Card>
        </div>
      </div>

      {/* ── Consolidated exposure (look-through) ──────────────────────── */}
      <div className="mt-4">
        <FundLookthroughSection instrumentId={fund.instrument_id} />
      </div>

      <p className="mt-4 text-[11px] text-text-muted">{fund.classification_note}</p>
    </div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex h-[20px] items-center border border-border-strong bg-field px-2 text-[10px] font-bold uppercase tracking-[0.05em] text-text-secondary">
      {children}
    </span>
  );
}

/** The remaining precomputed metrics as dense StatRows (KPIs excluded). */
function RiskRows({ risk }: { risk: FundRisk }) {
  const rows: { label: string; value: string; detail?: string }[] = [
    { label: "Return 1M", value: pct(risk.return_1m) },
    { label: "Return 3M", value: pct(risk.return_3m) },
    { label: "Return 3Y ann.", value: pct(risk.return_3y_ann) },
    { label: "Return 5Y ann.", value: pct(risk.return_5y_ann) },
    { label: "Max drawdown 1Y", value: pct(risk.max_drawdown_1y) },
    { label: "Max drawdown 3Y", value: pct(risk.max_drawdown_3y) },
    { label: "Sharpe 3Y", value: num(risk.sharpe_3y) },
    { label: "Sortino 1Y", value: num(risk.sortino_1y) },
    { label: "Calmar 3Y", value: num(risk.calmar_ratio_3y) },
    { label: "Alpha 1Y", value: pct(risk.alpha_1y) },
    { label: "Beta 1Y", value: num(risk.beta_1y) },
    { label: "Info ratio 1Y", value: num(risk.information_ratio_1y) },
    { label: "Tracking error 1Y", value: pct(risk.tracking_error_1y) },
    { label: "VaR 95 1M", value: pct(risk.var_95_1m) },
    { label: "CVaR 95 1M", value: pct(risk.cvar_95_1m) },
    { label: "CVaR 99 EVT", value: pct(risk.cvar_99_evt) },
    // Capture ratios arrive ×100 from the risk worker (95.3 = 95.3%) —
    // unlike the return/vol fractions; num(), not pct().
    { label: "Downside capture 1Y", value: num(risk.downside_capture_1y, 1) },
    { label: "Upside capture 1Y", value: num(risk.upside_capture_1y, 1) },
    { label: "Equity corr. 252d", value: num(risk.equity_correlation_252d) },
    {
      label: "Peer Sharpe pctl",
      value: num(risk.peer_sharpe_pctl, 0),
      ...(risk.peer_count !== null && {
        detail: `${risk.peer_count} peers · ${risk.peer_strategy_label ?? "—"}`,
      }),
    },
    { label: "Peer Sortino pctl", value: num(risk.peer_sortino_pctl, 0) },
    { label: "Peer return pctl", value: num(risk.peer_return_pctl, 0) },
    { label: "Peer drawdown pctl", value: num(risk.peer_drawdown_pctl, 0) },
    { label: "Manager score", value: num(risk.manager_score) },
    { label: "Elite", value: risk.elite_flag === null ? "—" : risk.elite_flag ? "Yes" : "No" },
  ];
  return (
    <>
      {rows.map((row) => (
        <StatRow key={row.label} label={row.label} value={row.value} detail={row.detail} />
      ))}
    </>
  );
}
