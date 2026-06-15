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
import { buildHcScatterOption } from "@/lib/charts/hc/scatter";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, KpiTile, valueTone } from "@/components/ui/panels";
import {
  AssetRefPicker,
  toAssetRef,
  useDefaultAssetY,
  type AssetRefDraft,
} from "@/components/statistics/AssetRefPicker";
import { DateRangeInputs, defaultDateRange } from "@/components/statistics/DateRangeInputs";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { ErrorPanel, ParamsPanel, RunButton } from "@/components/statistics/ui";

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
      <ParamsPanel>
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
      </ParamsPanel>

      {mutation.isPending ? (
        <BetaSkeleton />
      ) : mutation.isError ? (
        <ErrorPanel title="Regression failed" message={mutation.error.message} />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="ix-pad ix-fs border border-border bg-surface-2 text-text-muted">
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
    () => buildHcScatterOption(data.scatter, data.regression_line, labels, colors),
    [data.scatter, data.regression_line, labels, colors],
  );

  return (
    <div className="flex flex-col gap-px">
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Beta"
          value={formatNumber(regression.beta, 3)}
          tone="text-accent"
          detail={`${labels.y} on ${labels.x}`}
        />
        <KpiTile
          label="Alpha (daily)"
          value={formatPercent(regression.alpha, 3, { signed: true })}
          tone={valueTone(regression.alpha)}
        />
        <KpiTile label="Correlation (r)" value={formatNumber(regression.r, 3)} />
        <KpiTile label="Data points" value={formatNumber(regression.n_points, 0)} />
      </div>

      <Card title="Daily Returns" subtitle={`${labels.y} vs ${labels.x}`}>
        <HighchartsChart options={scatterOption} className="h-[440px] w-full" />
      </Card>
    </div>
  );
}

function BetaSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading regression"
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[84px] bg-surface-2" />
      <div className="h-[500px] bg-surface-2" />
    </div>
  );
}
