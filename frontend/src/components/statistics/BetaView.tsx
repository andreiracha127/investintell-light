"use client";

/**
 * Beta — regression of asset Y's daily returns on asset X's over a window.
 *
 * Each axis is a pseudo-asset (ticker or persisted portfolio). The backend
 * returns the scatter, the fitted line endpoints and the regression stats
 * render-ready; the frontend only draws.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { postBeta, type BetaRequest, type BetaResponse } from "@/lib/api/client";
import { buildScatterOption } from "@/lib/charts/scatter";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";
import { EChart } from "@/components/charts/EChart";
import { Card, StatRow } from "@/components/ui/panels";
import {
  AssetRefPicker,
  toAssetRef,
  useDefaultAssetY,
  type AssetRefDraft,
} from "@/components/statistics/AssetRefPicker";
import { DateRangeInputs, defaultDateRange } from "@/components/statistics/DateRangeInputs";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { ErrorPanel, RunButton } from "@/components/statistics/ui";

export function BetaView() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [draftX, setDraftX] = useState<AssetRefDraft>({
    kind: "ticker",
    ticker: "SPY",
  });
  const [draftY, setDraftY] = useDefaultAssetY();
  const [{ start, end }] = useState(defaultDateRange);
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);

  const mutation = useMutation({
    mutationFn: (body: BetaRequest) => postBeta(body),
  });

  const assetX = toAssetRef(draftX);
  const assetY = toAssetRef(draftY);
  const canRun =
    assetX !== null && assetY !== null && startDate !== "" && endDate !== "";
  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    mutation.mutate({
      asset_x: assetX,
      asset_y: assetY,
      start_date: startDate,
      end_date: endDate,
    });
  };

  return (
    <StatisticsShell>
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Beta
      </h1>

      <Card title="Parameters">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <AssetRefPicker label="X (independent)" value={draftX} onChange={setDraftX} />
          <AssetRefPicker label="Y (dependent)" value={draftY} onChange={setDraftY} />
          <DateRangeInputs
            start={startDate}
            end={endDate}
            onStartChange={setStartDate}
            onEndChange={setEndDate}
          />
          <RunButton
            pending={mutation.isPending}
            disabled={!canRun}
            onClick={onRun}
          />
        </div>
      </Card>

      {mutation.isPending ? (
        <BetaSkeleton />
      ) : mutation.isError ? (
        <ErrorPanel title="Regression failed" message={mutation.error.message} />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="text-[13px] text-text-muted">
          Pick the two assets and a date window, then press Run to regress
          Y&apos;s daily returns on X&apos;s.
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
  data: BetaResponse;
  colors: ChartColors;
}) {
  const { labels, regression } = data;

  const scatterOption = useMemo(
    () => buildScatterOption(data.scatter, data.regression_line, labels, colors),
    [data.scatter, data.regression_line, labels, colors],
  );

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-5 items-start">
      <Card title="Regression" subtitle={`${labels.y} on ${labels.x}`}>
        <p className="mt-1 mb-3">
          <span className="block text-[11px] uppercase tracking-[0.06em] text-text-muted">
            Beta
          </span>
          <span className="tabular-nums text-3xl font-bold text-accent">
            {formatNumber(regression.beta, 3)}
          </span>
        </p>
        <dl>
          <StatRow
            label="Alpha (daily)"
            value={formatPercent(regression.alpha, 3, { signed: true })}
          />
          <StatRow label="Correlation (r)" value={formatNumber(regression.r, 3)} />
          <StatRow label="Data points" value={formatNumber(regression.n_points, 0)} />
        </dl>
      </Card>

      <Card title="Daily Returns" subtitle={`${labels.y} vs ${labels.x}`}>
        <EChart option={scatterOption} className="h-[440px] w-full" />
      </Card>
    </div>
  );
}

function BetaSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading regression"
      className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-5 animate-pulse"
    >
      <div className="h-[280px] rounded-xl bg-surface-2" />
      <div className="h-[500px] rounded-xl bg-surface-2" />
    </div>
  );
}
