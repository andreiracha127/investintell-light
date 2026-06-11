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
import { buildRollingOption } from "@/lib/charts/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";
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
import { WindowInput, parseWindow } from "@/components/statistics/WindowInput";
import { ErrorPanel, RunButton } from "@/components/statistics/ui";

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
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Correlation
      </h1>

      <Card title="Parameters">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
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
        </div>
      </Card>

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
        <p className="text-[13px] text-text-muted">
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
      buildRollingOption(data.series, pairLabel, colors, {
        yMin: -1,
        yMax: 1,
      }),
    [data.series, pairLabel, colors],
  );

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-5 items-start">
      <Card title="Current Correlation" subtitle={pairLabel}>
        <p className="mt-1 mb-3">
          <span className="tabular-nums text-3xl font-bold text-accent">
            {formatNumber(data.current, 3)}
          </span>
        </p>
        <dl>
          <StatRow
            label="Rolling window"
            value={`${formatNumber(data.window, 0)} trading days`}
          />
        </dl>
      </Card>

      <Card title="Rolling Correlation" subtitle={pairLabel}>
        <EChart option={rollingOption} className="h-[400px] w-full" />
      </Card>
    </div>
  );
}

function CorrelationSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading correlation"
      className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-5 animate-pulse"
    >
      <div className="h-[200px] rounded-xl bg-surface-2" />
      <div className="h-[460px] rounded-xl bg-surface-2" />
    </div>
  );
}
