"use client";

/**
 * Stock Correlation — pairwise correlation heatmap of a persisted
 * portfolio's holdings over a trailing window. The backend returns the
 * matrix render-ready; the heatmap builder is reused from the portfolio page.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postStockCorrelation,
  type StockCorrelationRequest,
  type StockCorrelationResponse,
} from "@/lib/api/client";
import { buildHeatmapOption } from "@/lib/charts/heatmap";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatDate, formatNumber } from "@/lib/format";
import { EChart } from "@/components/charts/EChart";
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
    () => buildHeatmapOption(data, colors),
    [data, colors],
  );

  return (
    <Card
      title="Correlation Matrix"
      subtitle={`as of ${formatDate(data.as_of)} · ${formatNumber(data.window, 0)}d window`}
      actions={<HeatmapLegend />}
    >
      <EChart option={heatmapOption} className="h-[440px] w-full" />
    </Card>
  );
}
