"use client";

/**
 * Correlation Regime — portfolio-wide correlation structure read from
 * POST /correlation-regime: full pairwise matrix over the optimizer's aligned
 * returns, average correlation vs its trailing baseline, eigenvalue
 * concentration/absorption, diversification ratio, and per-pair contagion
 * flags. The portfolio's positions become the asset set; the backend computes
 * everything.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  fetchPortfolioOverview,
  postCorrelationRegime,
  type CorrelationRegimeRequest,
  type CorrelationRegimeResponse,
  type PortfolioOverview,
} from "@/lib/api/client";
import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, InfoDot, KpiTile } from "@/components/ui/panels";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { LABEL_CLASS, ErrorPanel, ParamsPanel, RunButton } from "@/components/statistics/ui";
import { retryPolicy } from "@/components/screener/shared";

/** Backend contract: 30..3650 calendar days, default 90. */
const WINDOW_DAYS_MIN = 30;
const WINDOW_DAYS_MAX = 3650;

function parseWindowDays(text: string): number | null {
  const value = Number(text.trim());
  return Number.isInteger(value) &&
    value >= WINDOW_DAYS_MIN &&
    value <= WINDOW_DAYS_MAX
    ? value
    : null;
}

/** Positions → discriminated asset refs (fund when catalogued, else equity). */
function positionsToAssets(
  overview: PortfolioOverview,
): NonNullable<CorrelationRegimeRequest["assets"]> {
  return overview.positions.map((position) =>
    position.instrument_id
      ? { kind: "fund" as const, id: position.instrument_id }
      : { kind: "equity" as const, ticker: position.ticker.toUpperCase() },
  );
}

export function CorrelationRegimeView() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [windowText, setWindowText] = useState("90");

  const overviewQuery = useQuery({
    queryKey: ["overview", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioOverview(portfolioId as number, signal),
    enabled: portfolioId !== null,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  const mutation = useMutation({
    mutationFn: (body: CorrelationRegimeRequest) => postCorrelationRegime(body),
  });

  const windowDays = parseWindowDays(windowText);
  const positionCount = overviewQuery.data?.positions.length ?? 0;
  const canRun = overviewQuery.data !== undefined && positionCount >= 2 && windowDays !== null;

  const onRun = () => {
    if (!canRun || mutation.isPending || !overviewQuery.data) return;
    mutation.mutate({
      assets: positionsToAssets(overviewQuery.data),
      window_days: windowDays,
    });
  };

  const windowInvalid = windowDays === null;

  return (
    <StatisticsShell>
      <ParamsPanel>
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} label="Portfolio" />
        <label className={`w-[120px] ${LABEL_CLASS}`}>
          Window (days)
          <span
            className={`flex h-[34px] items-center border-b bg-field focus-within:border-b-2 focus-within:border-accent ${
              windowInvalid ? "border-loss" : "border-border-strong"
            }`}
          >
            <input
              type="number"
              min={WINDOW_DAYS_MIN}
              max={WINDOW_DAYS_MAX}
              value={windowText}
              onChange={(e) => setWindowText(e.target.value)}
              aria-invalid={windowInvalid || undefined}
              className="h-full w-full bg-transparent px-2 text-[13px] tabular-nums text-text-primary outline-none"
            />
          </span>
        </label>
        <RunButton pending={mutation.isPending} disabled={!canRun} onClick={onRun} />
        {portfolioId !== null && positionCount < 2 && overviewQuery.data && (
          <span className="text-[12px] text-text-muted">
            Needs at least two positions.
          </span>
        )}
      </ParamsPanel>

      {mutation.isPending ? (
        <RegimeSkeleton />
      ) : mutation.isError ? (
        <ErrorPanel title="Correlation regime failed" message={mutation.error.message} />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="ix-pad ix-fs border border-border bg-surface-2 text-text-muted">
          Pick a portfolio and a trailing window, then press Run to read its
          correlation regime — matrix, concentration, diversification and
          contagion pairs.
        </p>
      )}
    </StatisticsShell>
  );
}

/* ── Results ──────────────────────────────────────────────────────────────── */

const STATUS_TONE: Record<string, string> = {
  diversified: "text-gain",
  moderate_concentration: "text-text-primary",
  high_concentration: "text-loss",
  normal: "text-gain",
  warning: "text-text-primary",
  critical: "text-loss",
};

function statusLabel(raw: string): string {
  return raw.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function Results({
  data,
  colors,
}: {
  data: CorrelationRegimeResponse;
  colors: ChartColors;
}) {
  const heatmapOption = useMemo(
    () =>
      buildHcHeatmapOption(
        { tickers: data.labels, matrix: data.correlation_matrix },
        colors,
        { diverging: true },
      ),
    [data.labels, data.correlation_matrix, colors],
  );

  const pairs = useMemo(
    () =>
      [...data.pair_correlations]
        .sort((a, b) => Math.abs(b.correlation_change) - Math.abs(a.correlation_change))
        .slice(0, 15),
    [data.pair_correlations],
  );

  const corrDelta = data.average_correlation - data.baseline_average_correlation;
  const { concentration } = data;

  return (
    <div className="flex flex-col gap-px">
      {!data.sufficient_data && (
        <p className="ix-pad border border-border border-l-[3px] border-l-[var(--color-loss)] bg-surface-2 text-[12.5px] text-text-secondary">
          Not enough aligned history for the requested window — read the results
          below as indicative only.
        </p>
      )}

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
        <KpiTile
          label="Regime"
          value={data.regime_shift_detected ? "Shift detected" : "Stable"}
          tone={data.regime_shift_detected ? "text-loss" : "text-gain"}
          tip="Flags when the current average correlation has moved materially away from its trailing baseline — correlations spiking together is the classic risk-off signature."
        />
        <KpiTile
          label="Avg correlation"
          value={formatNumber(data.average_correlation, 3)}
          detail={`baseline ${formatNumber(data.baseline_average_correlation, 3)} (${corrDelta >= 0 ? "+" : ""}${formatNumber(corrDelta, 3)})`}
          detailTone={corrDelta > 0.05 ? "text-loss" : "text-text-muted"}
          tip="Mean pairwise correlation across all instruments now, versus its trailing baseline."
        />
        <KpiTile
          label="Diversification ratio"
          value={formatNumber(data.diversification_ratio, 2)}
          tone={data.dr_alert ? "text-loss" : "text-text-primary"}
          detail={data.dr_alert ? "below alert threshold" : "healthy"}
          tip="Weighted average volatility divided by portfolio volatility. Higher is better; near 1 means positions move as one."
        />
        <KpiTile
          label="Concentration"
          value={statusLabel(concentration.concentration_status)}
          tone={STATUS_TONE[concentration.concentration_status] ?? "text-text-primary"}
          detail={`1st eigenvalue ${formatPercent(concentration.first_eigenvalue_ratio, 1)}`}
          tip="Share of total variance explained by the first principal component — how much a single factor drives the whole book."
        />
        <KpiTile
          label="Absorption"
          value={statusLabel(concentration.absorption_status)}
          tone={STATUS_TONE[concentration.absorption_status] ?? "text-text-primary"}
          detail={`ratio ${formatPercent(concentration.absorption_ratio, 1)}`}
          tip="Fraction of variance absorbed by the dominant eigenvectors. Elevated absorption means the portfolio is fragile to a single shock."
        />
        <KpiTile
          label="Universe"
          value={`${data.instrument_count}`}
          detail={`${data.window_days}-day window`}
          tip="Instruments with enough aligned history, and the trailing calendar window used."
        />
      </div>

      <Card
        title="Correlation matrix"
        subtitle={`${data.labels.length} instruments`}
        actions={
          <InfoDot tip="Pairwise return correlations over the trailing window. Diverging scale: accent = +1, neutral = 0, loss tone = −1." />
        }
      >
        <HighchartsChart
          options={heatmapOption}
          className="h-[440px] w-full"
          modules={["heatmap"]}
        />
      </Card>

      {pairs.length > 0 && (
        <Card
          title="Largest correlation moves"
          subtitle="current vs baseline"
          actions={
            <InfoDot tip="Pairs whose correlation moved the most against the baseline. Contagion marks pairs that were weakly linked and are now moving together." />
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-[length:var(--ix-fs)] tabular-nums">
              <thead>
                <tr className="border-b border-border-strong">
                  <th className="px-2.5 py-[7px] text-left text-[11px] font-semibold text-text-secondary">
                    Pair
                  </th>
                  <th className="px-2.5 py-[7px] text-right text-[11px] font-semibold text-text-secondary">
                    Baseline
                  </th>
                  <th className="px-2.5 py-[7px] text-right text-[11px] font-semibold text-text-secondary">
                    Current
                  </th>
                  <th className="px-2.5 py-[7px] text-right text-[11px] font-semibold text-text-secondary">
                    Δ
                  </th>
                  <th className="px-2.5 py-[7px] text-right text-[11px] font-semibold text-text-secondary">
                    Contagion
                  </th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((pair, i) => (
                  <tr
                    key={`${pair.label_a}-${pair.label_b}`}
                    className={`border-b border-border last:border-b-0 ${
                      i % 2 === 1 ? "bg-zebra" : ""
                    }`}
                  >
                    <td className="ix-cell px-2.5 font-bold text-text-primary">
                      {pair.label_a} × {pair.label_b}
                    </td>
                    <td className="ix-cell px-2.5 text-right text-text-secondary">
                      {formatNumber(pair.baseline_correlation, 3)}
                    </td>
                    <td className="ix-cell px-2.5 text-right text-text-primary">
                      {formatNumber(pair.current_correlation, 3)}
                    </td>
                    <td
                      className={`ix-cell px-2.5 text-right font-bold ${
                        pair.correlation_change > 0 ? "text-loss" : "text-gain"
                      }`}
                    >
                      {pair.correlation_change >= 0 ? "+" : ""}
                      {formatNumber(pair.correlation_change, 3)}
                    </td>
                    <td className="ix-cell px-2.5 text-right">
                      {pair.is_contagion ? (
                        <span className="border border-loss bg-loss/10 px-2 py-[1px] text-[10.5px] font-bold text-loss">
                          Contagion
                        </span>
                      ) : (
                        <span className="text-text-muted">--</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function RegimeSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading correlation regime"
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[84px] bg-surface-2" />
      <div className="h-[460px] bg-surface-2" />
      <div className="h-[220px] bg-surface-2" />
    </div>
  );
}
