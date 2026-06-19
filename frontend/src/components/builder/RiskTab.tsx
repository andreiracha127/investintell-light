"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel } from "@/components/screener/shared";
import { KpiTile, valueTone } from "@/components/ui/panels";
import {
  postPortfolioAnalysis,
  type OptimizeResponse,
  type PortfolioAnalysis,
  type PortfolioAnalysisRequest,
  type WeightOut,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { buildHcRiskBubbleOption } from "@/lib/charts/hc/bubble";
import { buildHcCumulativeOption } from "@/lib/charts/hc/cumulative";
import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
import { formatNumber, formatPercent } from "@/lib/format";

import { METRIC_COPY } from "./BuilderCopy";
import { buildActiveWeights } from "./activeWeights";
import { assetKey, type UniverseAsset } from "./assets";
import { ChartCard, TabSkeleton } from "./tabShared";

function weightTicker(
  weight: WeightOut,
  assetsByKey: Map<string, UniverseAsset>,
): string | null {
  if (weight.ticker) return weight.ticker;
  const known = assetsByKey.get(assetKey(weight.asset));
  if (known?.kind === "equity") return known.ticker;
  if (known?.kind === "fund" && known.ticker) return known.ticker;
  if (weight.asset.kind === "equity") return weight.asset.ticker ?? null;
  return null;
}

export function RiskTab({
  result,
  assetsByKey,
  colors,
}: {
  result: OptimizeResponse;
  assetsByKey: Map<string, UniverseAsset>;
  colors: ChartColors | null;
}) {
  const mutation = useMutation({
    mutationFn: (body: PortfolioAnalysisRequest) => postPortfolioAnalysis(body),
  });

  const analysisInput = useMemo(() => {
    const activeWeights = buildActiveWeights(result.weights);
    const positions: { ticker: string; weight: number }[] = [];
    let missing = 0;

    for (const weight of activeWeights.positions) {
      const ticker = weightTicker(weight.source, assetsByKey);
      if (!ticker) {
        missing += 1;
        continue;
      }
      positions.push({ ticker, weight: weight.weight });
    }

    return {
      missing,
      activeCount: activeWeights.positions.length,
      dropped: activeWeights.dropped,
      request:
        missing === 0 && activeWeights.isValid
          ? ({
              positions,
              mode: "weights",
              benchmark: "SPY",
              range: "1Y",
            } satisfies PortfolioAnalysisRequest)
          : null,
    };
  }, [result.weights, assetsByKey]);

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current || !analysisInput.request) return;
    firedRef.current = true;
    mutation.mutate(analysisInput.request);
  }, [analysisInput.request, mutation]);

  if (analysisInput.missing > 0) {
    return (
      <ErrorPanel
        title="Cannot analyze risk"
        message={`Could not resolve a ticker for ${analysisInput.missing} position${
          analysisInput.missing === 1 ? "" : "s"
        }.`}
        onRetry={() => undefined}
      />
    );
  }

  if (analysisInput.activeCount < 2) {
    return (
      <ErrorPanel
        title="Cannot analyze risk"
        message="At least two active positions above the weight floor are required."
        onRetry={() => undefined}
      />
    );
  }

  if (mutation.isIdle || mutation.isPending) {
    return <TabSkeleton label="Analyzing portfolio risk" />;
  }

  if (mutation.isError) {
    return (
      <ErrorPanel
        title="Risk analysis failed"
        message={mutation.error.message}
        onRetry={() => {
          if (analysisInput.request) mutation.mutate(analysisInput.request);
        }}
      />
    );
  }

  return <RiskBody data={mutation.data} colors={colors} />;
}

function RiskBody({
  data,
  colors,
}: {
  data: PortfolioAnalysis;
  colors: ChartColors | null;
}) {
  const { stats } = data;
  const contributionsOption = colors
    ? buildHcRiskBubbleOption(data.risk_contributions, colors)
    : null;
  const heatmapOption = colors
    ? buildHcHeatmapOption(data.correlation_matrix, colors, {
        diverging: true,
        // Diverging scale: blue at -1, surface at 0, accent at +1 (mockup).
        negativeColor: colors.blue,
        zeroColor: colors.surface,
      })
    : null;
  const cumulativeOption = colors
    ? buildHcCumulativeOption(
        {
          asset: data.benchmark_comparison.portfolio,
          benchmark: data.benchmark_comparison.benchmark,
        },
        "Portfolio",
        "S&P 500",
        colors,
        { growthOf100: true },
      )
    : null;

  return (
    <div className="flex flex-col gap-px">
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label={METRIC_COPY.vol_ann.label}
          value={formatPercent(stats.annualized_volatility)}
          tip={METRIC_COPY.vol_ann.tip}
          tone="text-accent"
        />
        <KpiTile
          label={METRIC_COPY.sharpe_ratio.label}
          value={formatNumber(stats.sharpe_ratio)}
          tip={METRIC_COPY.sharpe_ratio.tip}
        />
        <KpiTile
          label={METRIC_COPY.sortino_ratio.label}
          value={formatNumber(stats.sortino_ratio)}
          tip={METRIC_COPY.sortino_ratio.tip}
        />
        <KpiTile
          label={METRIC_COPY.cvar_95.label}
          value={formatPercent(stats.cvar_95)}
          detail="1-day, worst 5%"
          tip={METRIC_COPY.cvar_95.tip}
        />
        <KpiTile
          label={METRIC_COPY.max_drawdown.label}
          value={formatPercent(stats.max_drawdown.depth)}
          tip={METRIC_COPY.max_drawdown.tip}
          tone="text-loss"
        />
        <KpiTile
          label={METRIC_COPY.diversification_ratio.label}
          value={formatNumber(stats.diversification_ratio)}
          tip={METRIC_COPY.diversification_ratio.tip}
        />
        <KpiTile
          label={METRIC_COPY.information_ratio.label}
          value={formatNumber(stats.information_ratio)}
          tip={METRIC_COPY.information_ratio.tip}
          tone={valueTone(stats.information_ratio)}
        />
        <KpiTile
          label={METRIC_COPY.beta.label}
          value={formatNumber(stats.beta)}
          tip={METRIC_COPY.beta.tip}
        />
      </div>

      <ChartCard
        title="Where the risk comes from"
        subtitle="each holding's share of total portfolio risk"
        tip="Each bubble is a holding's share of total portfolio risk — not the same as its weight. A small, volatile holding can carry outsized risk."
      >
        {contributionsOption ? (
          <HighchartsChart
            options={contributionsOption}
            className="h-[440px] w-full"
            isEmpty={data.risk_contributions.length === 0}
            emptyMessage="No risk contributions returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </ChartCard>

      <ChartCard
        title="How holdings move together"
        tip="Correlation from −1 (move opposite) to +1 (move together). Lower correlations mean more diversification."
      >
        {heatmapOption ? (
          <>
            <HighchartsChart
              options={heatmapOption}
              className="h-[360px] w-full"
              isEmpty={data.correlation_matrix.tickers.length === 0}
              emptyMessage="No correlation matrix returned."
            />
            {/* Diverging −1 → 0 → +1 gradient legend (tokens only): grey-blue
                negative end, surface zero, accent positive. */}
            <div className="mt-3 flex items-center justify-center gap-2 text-[10px] text-text-muted">
              <span>−1.0</span>
              <span
                className="h-2 w-[160px]"
                style={{
                  background:
                    "linear-gradient(90deg, var(--color-chart-blue), var(--color-surface-3), var(--color-accent))",
                }}
              />
              <span>+1.0</span>
            </div>
          </>
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </ChartCard>

      <ChartCard title="Growth of $100 — portfolio vs. S&P 500">
        {cumulativeOption ? (
          <HighchartsChart
            options={cumulativeOption}
            className="h-[320px] w-full"
            isEmpty={data.benchmark_comparison.portfolio.length === 0}
            emptyMessage="No comparison series returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </ChartCard>
    </div>
  );
}
