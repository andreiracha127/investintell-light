"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel } from "@/components/screener/shared";
import { Card, KpiTile, valueTone } from "@/components/ui/panels";
import {
  postPortfolioAnalysis,
  type OptimizeResponse,
  type PortfolioAnalysis,
  type PortfolioAnalysisRequest,
  type WeightOut,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { buildHcRiskContributionsOption } from "@/lib/charts/hc/contributions";
import { buildHcCumulativeOption } from "@/lib/charts/hc/cumulative";
import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
import { formatNumber, formatPercent } from "@/lib/format";

import { buildActiveWeights } from "./activeWeights";
import { assetKey, type UniverseAsset } from "./assets";
import { TabSkeleton } from "./tabShared";

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
    ? buildHcRiskContributionsOption(data.risk_contributions, colors)
    : null;
  const heatmapOption = colors
    ? buildHcHeatmapOption(data.correlation_matrix, colors)
    : null;
  const cumulativeOption = colors
    ? buildHcCumulativeOption(
        {
          asset: data.benchmark_comparison.portfolio,
          benchmark: data.benchmark_comparison.benchmark,
        },
        "Portfolio",
        "SPY",
        colors,
      )
    : null;

  return (
    <div className="flex flex-col gap-px">
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Vol (ann.)"
          value={formatPercent(stats.annualized_volatility)}
          tone="text-accent"
        />
        <KpiTile label="Sharpe" value={formatNumber(stats.sharpe_ratio)} />
        <KpiTile label="Sortino" value={formatNumber(stats.sortino_ratio)} />
        <KpiTile
          label="CVaR 95"
          value={formatPercent(stats.cvar_95)}
          detail="1-day, worst 5%"
        />
        <KpiTile
          label="Max drawdown"
          value={formatPercent(stats.max_drawdown.depth)}
          tone="text-loss"
        />
        <KpiTile
          label="Diversification"
          value={formatNumber(stats.diversification_ratio)}
        />
        <KpiTile
          label="Information ratio"
          value={formatNumber(stats.information_ratio)}
          tone={valueTone(stats.information_ratio)}
        />
        <KpiTile label="Beta (SPY)" value={formatNumber(stats.beta)} />
      </div>

      <Card title="Risk contribution by asset">
        {contributionsOption ? (
          <HighchartsChart
            options={contributionsOption}
            className="h-[320px] w-full"
            isEmpty={data.risk_contributions.length === 0}
            emptyMessage="No risk contributions returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </Card>

      <Card title="Correlation matrix">
        {heatmapOption ? (
          <HighchartsChart
            options={heatmapOption}
            className="h-[360px] w-full"
            isEmpty={data.correlation_matrix.tickers.length === 0}
            emptyMessage="No correlation matrix returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </Card>

      <Card title="Cumulative return - portfolio vs SPY">
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
      </Card>
    </div>
  );
}
