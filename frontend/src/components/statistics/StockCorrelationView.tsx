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
import { ErrorPanel, RunButton } from "@/components/statistics/ui";

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
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Stock Correlation
      </h1>

      <Card title="Parameters">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <PortfolioSelect value={portfolioId} onChange={setPortfolioId} />
          <WindowInput value={windowText} onChange={setWindowText} />
          <RunButton
            pending={mutation.isPending}
            disabled={!canRun}
            onClick={onRun}
          />
        </div>
      </Card>

      {mutation.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading stock correlation"
          className="h-[480px] rounded-xl bg-surface-2 animate-pulse"
        />
      ) : mutation.isError ? (
        <ErrorPanel
          title="Stock correlation failed"
          message={mutation.error.message}
        />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="text-[13px] text-text-muted">
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
    <Card title="Correlation Matrix">
      <div className="mb-2 flex items-center gap-2">
        <span className="px-1.5 py-px rounded-[4px] bg-surface-3 border border-border text-[10px] text-text-muted">
          as of {formatDate(data.as_of)} · {formatNumber(data.window, 0)}d window
        </span>
      </div>
      <EChart option={heatmapOption} className="h-[440px] w-full" />
    </Card>
  );
}
