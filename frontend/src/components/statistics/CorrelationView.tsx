"use client";

/**
 * Correlation — rolling correlation of two pseudo-assets' daily returns.
 *
 * The backend warms up the rolling window on a pre-start pad and returns the
 * in-range series plus the current (latest) value; the frontend only draws.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postCorrelation,
  type CorrelationRequest,
  type CorrelationResponse,
} from "@/lib/api/client";
import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, KpiTile } from "@/components/ui/panels";
import {
  AssetRefPicker,
  toAssetRef,
  useDefaultAssetY,
  type AssetRefDraft,
} from "@/components/statistics/AssetRefPicker";
import { DateRangeInputs, defaultDateRange } from "@/components/statistics/DateRangeInputs";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { WindowInput, parseWindow } from "@/components/statistics/WindowInput";
import { ErrorPanel, ParamsPanel, RunButton } from "@/components/statistics/ui";

export function CorrelationView() {
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
  const [windowText, setWindowText] = useState("63");

  const mutation = useMutation({
    mutationFn: (body: CorrelationRequest) => postCorrelation(body),
  });

  const assetX = toAssetRef(draftX);
  const assetY = toAssetRef(draftY);
  const window = parseWindow(windowText);
  const canRun =
    assetX !== null &&
    assetY !== null &&
    window !== null &&
    startDate !== "" &&
    endDate !== "";
  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    mutation.mutate({
      asset_x: assetX,
      asset_y: assetY,
      start_date: startDate,
      end_date: endDate,
      window,
    });
  };

  return (
    <StatisticsShell>
      <ParamsPanel>
        <AssetRefPicker label="X" value={draftX} onChange={setDraftX} />
        <AssetRefPicker label="Y" value={draftY} onChange={setDraftY} />
        <DateRangeInputs
          start={startDate}
          end={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />
        <WindowInput value={windowText} onChange={setWindowText} />
        <RunButton
          pending={mutation.isPending}
          disabled={!canRun}
          onClick={onRun}
        />
      </ParamsPanel>

      {mutation.isPending ? (
        <CorrelationSkeleton />
      ) : mutation.isError ? (
        <ErrorPanel
          title="Correlation failed"
          message={mutation.error.message}
        />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="ix-pad ix-fs border border-border bg-surface-2 text-text-muted">
          Pick the two assets, a date window and a rolling window, then press
          Run to chart their rolling correlation.
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
  data: CorrelationResponse;
  colors: ChartColors;
}) {
  const { labels } = data;
  const pairLabel = `${labels.x} × ${labels.y}`;

  const rollingOption = useMemo(
    () =>
      buildHcRollingOption(data.series, pairLabel, colors, {
        yMin: -1,
        yMax: 1,
      }),
    [data.series, pairLabel, colors],
  );

  return (
    <div className="flex flex-col gap-px">
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Current correlation"
          value={formatNumber(data.current, 3)}
          tone="text-accent"
          detail={pairLabel}
        />
        <KpiTile
          label="Rolling window"
          value={formatNumber(data.window, 0)}
          detail="trading days"
        />
      </div>

      <Card title="Rolling Correlation" subtitle={pairLabel}>
        <HighchartsChart options={rollingOption} className="h-[400px] w-full" />
      </Card>
    </div>
  );
}

function CorrelationSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading correlation"
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[84px] bg-surface-2" />
      <div className="h-[460px] bg-surface-2" />
    </div>
  );
}
