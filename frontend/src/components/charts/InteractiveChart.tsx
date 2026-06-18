"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import type { Chart } from "highcharts";

import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { HighchartsStockChart } from "@/components/charts/HighchartsStockChart";
import {
  RANGE_PRESETS,
  fetchFundHistory,
  fetchStockHistory,
  type RangePreset,
} from "@/lib/api/client";
import {
  addCompareSelection,
  buildHcPriceCoreOption,
  buildHcPriceStockOption,
  removeCompareSelection,
  type PriceBar,
  type PriceChartType,
  type PriceCompareSelection,
  type PriceMode,
  type PricePeriod,
} from "@/lib/charts/hc/priceStock";
import {
  applyTickToLiveChart,
  mergeTickIntoBarsResult,
  parseTickTimeMs,
} from "@/lib/charts/hc/priceStockLive";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { onFeedStatus, subscribeTicks, type FeedStatus } from "@/lib/livefeed/client";

const PERIODS: PricePeriod[] = ["D", "W", "M"];
const TYPES: { id: PriceChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "ohlc", label: "OHLC" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
];

export function InteractiveChart({
  symbol,
  bars,
  range,
  onRangeChange,
  mode = "ohlcv",
  className,
  chartAreaClassName = "h-[58vh] min-h-[380px]",
}: {
  symbol: string;
  bars: PriceBar[];
  range: RangePreset;
  onRangeChange: (next: RangePreset) => void;
  mode?: PriceMode;
  className?: string;
  /** Sizing classes for the chart canvas area (height / aspect-ratio). */
  chartAreaClassName?: string;
}) {
  const chartRef = useRef<Chart | null>(null);
  const [colors, setColors] = useState<ChartColors | null>(null);
  const [liveBars, setLiveBars] = useState<PriceBar[]>(bars);
  const liveBarsRef = useRef<PriceBar[]>(bars);
  const [period, setPeriod] = useState<PricePeriod>("D");
  const [type, setType] = useState<PriceChartType>(mode === "nav" ? "line" : "candles");
  const [overlays, setOverlays] = useState({ sma20: true, sma50: false });
  const [panes, setPanes] = useState({ volume: mode !== "nav", rsi: false });
  const [scale, setScale] = useState({ log: false, pct: false });
  const [compares, setCompares] = useState<PriceCompareSelection[]>([]);
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<FeedStatus>("off");

  // Render params read inside the live-tick callback. Kept in a ref so changing
  // type/period/volume does NOT re-run the subscribeTicks effect (which would
  // tear down and re-open the WebSocket on every Candles/OHLC/Line, D/W/M, VOL
  // click). The ref is updated synchronously on every render below.
  const renderParamsRef = useRef({ type, period, volume: panes.volume });
  renderParamsRef.current = { type, period, volume: panes.volume };

  // Coalesce live-tick redraws: at most one incremental chart update per frame.
  // pendingTickRef holds the latest bar + whether it was appended; rafRef holds
  // the scheduled frame (null when nothing is queued).
  const rafRef = useRef<number | null>(null);
  const pendingTickRef = useRef<{ bar: PriceBar; appended: boolean } | null>(null);

  useEffect(() => {
    setColors(chartColors());
  }, []);

  useEffect(() => {
    setLiveBars(bars);
    liveBarsRef.current = bars;
  }, [bars]);

  useEffect(() => {
    liveBarsRef.current = liveBars;
  }, [liveBars]);

  useEffect(() => {
    if (mode === "nav" && (type === "candles" || type === "ohlc")) {
      setType("line");
    }
    if (mode === "nav" && panes.volume) {
      setPanes((current) => ({ ...current, volume: false }));
    }
  }, [mode, panes.volume, type]);

  useEffect(() => onFeedStatus(setFeed), []);

  const compareQueries = useQueries({
    queries: compares.map((compare) => ({
      queryKey: [
        "compare-history",
        compare.kind,
        compare.symbol,
        compare.instrumentId,
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        compare.instrumentId &&
        (compare.kind === "mutual_fund" || compare.kind === "mmf")
          ? fetchFundHistory(compare.instrumentId, 2520, signal)
          : fetchStockHistory(compare.symbol, 2520, signal),
      staleTime: 60 * 60 * 1000,
    })),
  });

  const compareData = useMemo(() => {
    const out: Record<string, PriceBar[]> = {};
    compares.forEach((compare, index) => {
      const data = compareQueries[index]?.data;
      if (data?.bars?.length) out[compare.key] = data.bars;
    });
    return out;
  }, [compares, compareQueries]);

  const usesStockChart = mode !== "nav";
  const options = useMemo(() => {
    if (!colors) return null;
    const builder = usesStockChart ? buildHcPriceStockOption : buildHcPriceCoreOption;
    return builder({
      symbol,
      bars: liveBars,
      mode,
      type,
      period,
      range,
      overlays,
      panes,
      scale,
      compares,
      compareData,
      colors,
      // No onVisibleRangeChange: the backend returns exactly the range window,
      // so inferring the range from the visible extents always reads as "MAX"
      // (whole dataset visible) and snaps the chart back to MAX on every range
      // click. The toolbar range buttons are the sole source of truth.
    });
  }, [
    colors,
    symbol,
    liveBars,
    mode,
    type,
    period,
    range,
    overlays,
    panes,
    scale,
    compares,
    compareData,
    usesStockChart,
  ]);

  useEffect(() => {
    if (!live || mode === "nav" || !symbol) return;

    const flush = () => {
      rafRef.current = null;
      const pending = pendingTickRef.current;
      pendingTickRef.current = null;
      if (!pending || !chartRef.current) return;
      const { type, volume } = renderParamsRef.current;
      applyTickToLiveChart({
        chart: chartRef.current,
        bar: pending.bar,
        appended: pending.appended,
        type,
        showVolume: mode === "ohlcv" && volume,
        redraw: true,
      });
    };

    const unsubscribe = subscribeTicks(symbol, (tick) => {
      const timeMs = parseTickTimeMs(tick.time);
      // Pure state computation: derive the next bars from the current ref, then
      // commit via ref + setState. No chart side-effects inside the updater.
      const { bars: next, appended } = mergeTickIntoBarsResult(liveBarsRef.current, {
        price: tick.price,
        size: tick.size,
        timeMs,
      });
      if (!next.length) return;
      liveBarsRef.current = next;
      setLiveBars(next);

      // Queue an incremental redraw, coalesced to one per animation frame.
      // Carry forward `appended` if any tick this frame started a new bar, so a
      // day-boundary append is never dropped by a later same-day update.
      pendingTickRef.current = {
        bar: next[next.length - 1],
        appended: appended || (pendingTickRef.current?.appended ?? false),
      };
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(flush);
      }
    });

    return () => {
      unsubscribe();
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      pendingTickRef.current = null;
    };
  }, [symbol, live, mode]);

  const typeOptions =
    mode === "nav" ? TYPES.filter((entry) => entry.id === "line" || entry.id === "area") : TYPES;

  const btn = (active: boolean) =>
    `px-2 h-7 text-[11px] border-r border-border last:border-r-0 transition-colors ${
      active ? "bg-accent font-bold text-on-accent" : "text-text-muted hover:bg-layer-hover hover:text-text-primary"
    }`;

  const group = "flex items-stretch border border-border-strong";

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2 border border-b-0 border-border bg-surface-1 px-2 py-1.5 text-[11px]">
        <div role="group" aria-label="Chart type" className={group}>
          {typeOptions.map((entry) => (
            <button
              key={entry.id}
              type="button"
              aria-pressed={type === entry.id}
              className={btn(type === entry.id)}
              onClick={() => setType(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Period" className={group}>
          {PERIODS.map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={period === entry}
              className={btn(period === entry)}
              onClick={() => setPeriod(entry)}
            >
              {entry}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Range" className={group}>
          {RANGE_PRESETS.map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={range === entry}
              className={btn(range === entry)}
              onClick={() => onRangeChange(entry)}
            >
              {entry}
            </button>
          ))}
        </div>
        {usesStockChart && (
          <div role="group" aria-label="Indicators" className={group}>
            <button
              type="button"
              aria-pressed={overlays.sma20}
              className={btn(overlays.sma20)}
              onClick={() => setOverlays((current) => ({ ...current, sma20: !current.sma20 }))}
            >
              SMA20
            </button>
            <button
              type="button"
              aria-pressed={overlays.sma50}
              className={btn(overlays.sma50)}
              onClick={() => setOverlays((current) => ({ ...current, sma50: !current.sma50 }))}
            >
              SMA50
            </button>
            <button
              type="button"
              aria-pressed={panes.volume}
              className={btn(panes.volume)}
              onClick={() => setPanes((current) => ({ ...current, volume: !current.volume }))}
            >
              VOL
            </button>
            <button
              type="button"
              aria-pressed={panes.rsi}
              className={btn(panes.rsi)}
              onClick={() => setPanes((current) => ({ ...current, rsi: !current.rsi }))}
            >
              RSI
            </button>
          </div>
        )}
        <div role="group" aria-label="Scale" className={group}>
          <button
            type="button"
            aria-pressed={scale.log}
            className={btn(scale.log)}
            onClick={() => setScale((current) => ({ ...current, log: !current.log, pct: false }))}
          >
            Log
          </button>
          <button
            type="button"
            aria-pressed={scale.pct}
            className={btn(scale.pct)}
            onClick={() => setScale((current) => ({ ...current, pct: !current.pct, log: false }))}
          >
            %
          </button>
        </div>
        <SymbolSearchInput
          active={null}
          onSelect={(item) => {
            setCompares((current) => addCompareSelection(current, item));
            setScale((current) => ({ ...current, pct: true, log: false }));
          }}
        />
        <div className="flex flex-wrap items-center gap-1">
          {compares.map((compare) => (
            <button
              key={compare.key}
              type="button"
              className="h-7 border border-border-strong bg-field px-2 text-[11px] text-text-secondary hover:bg-layer-hover hover:text-text-primary"
              onClick={() => setCompares((current) => removeCompareSelection(current, compare.key))}
              aria-label={`Remove comparison ${compare.label}`}
            >
              {compare.label} x
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {usesStockChart && (
          <button
            type="button"
            aria-pressed={live}
            onClick={() => setLive((value) => !value)}
            className={`flex h-7 items-center gap-1.5 border border-border-strong px-2 text-[11px] ${
              live && feed === "live" ? "text-gain" : "text-text-muted"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live && feed === "live" ? "bg-gain" : "bg-border-strong"
              }`}
            />
            {live && feed === "live" ? "LIVE" : "EOD"}
          </button>
        )}
      </div>

      <div className={`relative border border-border bg-surface-1 ${chartAreaClassName}`}>
        {options ? (
          usesStockChart ? (
            <HighchartsStockChart
              options={options}
              className="h-full w-full"
              isEmpty={liveBars.length === 0}
              emptyMessage="No price or NAV history in the synced window."
              onReady={(chart) => {
                chartRef.current = chart;
              }}
            />
          ) : (
            <HighchartsChart
              options={options}
              className="h-full w-full"
              isEmpty={liveBars.length === 0}
              emptyMessage="No price or NAV history in the synced window."
              onReady={(chart) => {
                chartRef.current = chart;
              }}
            />
          )
        ) : (
          <div className="flex h-full items-center justify-center text-[13px] text-text-muted">
            Loading chart...
          </div>
        )}
      </div>
    </div>
  );
}
