"use client";

/**
 * Native Highstock wrapper for the stock price chart. Unlike the generic
 * `HighchartsStockChart` (which calls `chart.update(options)` on every option
 * change), this component creates the chart ONCE via `buildStockOptions` and
 * then mutates it surgically:
 *   - new `symbol`/`bars`  → `series.setData(...)` on the price + volume series
 *   - compare add/remove   → `chart.addSeries(...)` / `chart.get(id).remove()`
 *   - log toggle           → `priceAxis.update({ type })`
 *   - live ticks           → `applyTickToStockChart` coalesced via rAF
 * Creating once is the bug fix: a full `chart.update(buildStockOptions(...))`
 * tears down user drawings/annotations. Series type and indicators are driven
 * by the native stock-tools GUI; only compare/scale/live need custom chrome.
 *
 * Module dependencies (import order matters — stock-tools.js depends on all
 * modules below it):
 *   highstock → highcharts-more → indicators-all → annotations-advanced →
 *   drag-panes → price-indicator → full-screen → stock-tools
 */
import { useEffect, useRef, useState } from "react";
import type { Chart, Series, YAxisOptions } from "highcharts";

// Native Highstock stock-tools GUI stylesheets (drawing/annotation toolbar +
// popups). The modules themselves are registered in the create effect below.
import "highcharts/css/stocktools/gui.css";
import "highcharts/css/annotations/popup.css";
// Graphite chrome on top of the native GUI (tokens from globals.css).
import "./stock-chart.css";

import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
import { chartColors } from "@/lib/charts/chartColors";
import { highchartsTheme } from "@/lib/charts/hc/theme";
import {
  buildStockOptions,
  rangeButtonIndexForPreset,
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  stockTypeFromSeries,
  toMainSeriesData,
  toVolumeSeriesData,
  type StockCompare,
} from "@/lib/charts/hc/stock";
import {
  applyTickToStockChart,
  mergeTickIntoBars,
  parseTickTimeMs,
} from "@/lib/charts/hc/stockLive";
import {
  fetchStockHistory,
  type HistoryBar,
  type RangePreset,
  type SymbolSearchResult,
} from "@/lib/api/client";
import {
  onFeedStatus,
  subscribeTicks,
  type FeedStatus,
} from "@/lib/livefeed/client";

// Series type/showVolume are fixed at create time and never change reactively
// (the native GUI drives type changes), so the live-tick callback can use these
// constants directly without a render-params ref.
const INITIAL_TYPE = "candles" as const;
const SHOW_VOLUME = true;
const MAX_COMPARE = 4;

interface CompareEntry extends StockCompare {
  /** Loaded bars (empty until the history fetch resolves). */
  bars: HistoryBar[];
}

function compareKey(item: SymbolSearchResult): string {
  return `${item.symbol.toUpperCase()}:${item.instrument_id ?? ""}:${item.kind ?? ""}`;
}

const FEED_BADGE: Record<FeedStatus, { label: string; live: boolean }> = {
  live: { label: "LIVE", live: true },
  connecting: { label: "EOD", live: false },
  error: { label: "EOD", live: false },
  off: { label: "EOD", live: false },
};

// Id of the always-on High/Low marker so we can replace it on refresh WITHOUT
// touching user-drawn annotations (which carry their own ids).
const AUTO_HL_ID = "auto-hl";

type AnnotationChart = Chart & {
  addAnnotation?: (options: unknown, redraw?: boolean) => unknown;
  removeAnnotation?: (idOrAnnotation: string) => void;
};

/**
 * Draws (or redraws) the decorative High/Low markers + connecting trendline
 * over the CURRENTLY VISIBLE window — matching the golden reference, which
 * recomputes High/Low for the range on view. Computed from `bars` so it stays
 * decoupled from Highcharts point internals, and fully guarded: a decorative
 * annotation must never throw and break the live chart.
 */
function refreshHighLowAnnotation(
  chart: Chart | null,
  bars: HistoryBar[],
  colors: ReturnType<typeof chartColors> | null,
): void {
  const ac = chart as AnnotationChart | null;
  if (!ac?.addAnnotation || !ac.removeAnnotation || !colors) return;
  try {
    ac.removeAnnotation(AUTO_HL_ID);
  } catch {
    /* not drawn yet — nothing to remove */
  }
  try {
    const ext = chart?.xAxis?.[0]?.getExtremes?.();
    const lo = typeof ext?.min === "number" ? ext.min : -Infinity;
    const hi = typeof ext?.max === "number" ? ext.max : Infinity;
    const view = bars.filter((b) => b.t >= lo && b.t <= hi);
    const src = view.length >= 2 ? view : bars;
    if (src.length < 2) return;
    let hiI = 0;
    let loI = 0;
    for (let i = 1; i < src.length; i++) {
      if (src[i].h > src[hiI].h) hiI = i;
      if (src[i].l < src[loI].l) loI = i;
    }
    const H = src[hiI];
    const L = src[loI];
    const fmt = (n: number) => n.toFixed(2);
    ac.addAnnotation(
      {
        id: AUTO_HL_ID,
        draggable: "",
        labelOptions: {
          backgroundColor: colors.surface,
          borderColor: colors.grid,
          borderRadius: 6,
          padding: 5,
          style: { color: colors.text, fontSize: "10px" },
        },
        labels: [
          { point: { x: H.t, y: H.h, xAxis: 0, yAxis: 0 }, text: `High ${fmt(H.h)}` },
          { point: { x: L.t, y: L.l, xAxis: 0, yAxis: 0 }, text: `Low ${fmt(L.l)}` },
        ],
        shapes: [
          {
            type: "path",
            stroke: colors.accent,
            strokeWidth: 1.4,
            dashStyle: "Dash",
            points: [
              { x: L.t, y: L.l, xAxis: 0, yAxis: 0 },
              { x: H.t, y: H.h, xAxis: 0, yAxis: 0 },
            ],
          },
        ],
      },
      true,
    );
  } catch {
    /* never let a decorative annotation break the chart */
  }
}

/**
 * Make EVERY drawn annotation selectable (click → edit/delete toolbar).
 *
 * Highcharts wires the "select annotation" handler (which opens the stock-tools
 * edit/delete toolbar and exposes the Remove button) onto the BASE Annotation
 * class only. The advanced types registered by annotations-advanced — fibonacci,
 * pitchfork, measure, crookedLine, elliottWave, tunnel, infinityLine,
 * timeCycles, fibonacciTimeZones, verticalLine, basicAnnotation — are created
 * after that wiring runs, and their own `defaultOptions.events` shadow the base,
 * leaving them with NO click handler: a drawn Fibonacci can't be selected or
 * deleted. Propagate the base class's events (click/touchstart/touchend) onto
 * every registered type. Idempotent — safe to run on every chart mount.
 */
type AnnotationProto = {
  prototype?: { defaultOptions?: { events?: Record<string, unknown> } };
};
function ensureAnnotationsSelectable(highcharts: unknown): void {
  const Annotation = (highcharts as { Annotation?: AnnotationProto & {
    types?: Record<string, AnnotationProto>;
  } }).Annotation;
  const baseEvents = Annotation?.prototype?.defaultOptions?.events;
  const types = Annotation?.types;
  if (!baseEvents || !baseEvents.click || !types) return;
  for (const key of Object.keys(types)) {
    const defaults = types[key]?.prototype?.defaultOptions;
    if (defaults) {
      defaults.events = { ...(defaults.events ?? {}), ...baseEvents };
    }
  }
}

export function StockChart({
  symbol,
  bars,
  initialRange,
  onRangeChange,
  className,
  isEmpty,
  emptyMessage,
}: {
  symbol: string;
  bars: HistoryBar[];
  initialRange: RangePreset;
  onRangeChange: (preset: RangePreset) => void;
  className?: string;
  isEmpty?: boolean;
  emptyMessage?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  // Resolved design tokens captured at create time, reused by the High/Low
  // annotation refresh (which runs outside the create effect's closure).
  const colorsRef = useRef<ReturnType<typeof chartColors> | null>(null);

  // Current bars for the live-tick callback; kept in a ref so ticks merge onto
  // the latest data without re-running the subscribe effect.
  const barsRef = useRef<HistoryBar[]>(bars);

  // onRangeChange/initialRange read inside the create effect (which runs once);
  // refs keep them current without rebuilding the chart.
  const onRangeChangeRef = useRef(onRangeChange);
  onRangeChangeRef.current = onRangeChange;
  const initialRangeRef = useRef(initialRange);

  // Highstock applies `rangeSelector.selected` during init, which fires
  // `afterSetExtremes` with `e.rangeSelectorButton` populated → one synthetic
  // onRangeButtonClick on every mount. Swallow that first emission so we don't
  // emit a redundant router.replace on load; genuine user clicks (all later
  // emissions) pass through unchanged.
  const mountedRef = useRef(false);

  // Coalesce live-tick redraws to one incremental update per animation frame.
  const rafRef = useRef<number | null>(null);
  const pendingTickRef = useRef<{ bar: HistoryBar; appended: boolean } | null>(null);

  const [compares, setCompares] = useState<CompareEntry[]>([]);
  const comparesRef = useRef<CompareEntry[]>(compares);
  comparesRef.current = compares;

  const [feed, setFeed] = useState<FeedStatus>("off");

  // ── Create the chart ONCE ────────────────────────────────────────────────
  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void (async () => {
      // ESM build so Stock modules register on the same Highcharts singleton.
      // Import order matters: stock-tools.js depends on all modules below it.
      const mod = await import("highcharts/esm/highstock.js");
      await import("highcharts/esm/highcharts-more.js");
      // Native indicators (RSI/MACD/Bollinger/…) the user adds via the GUI.
      await import("highcharts/esm/indicators/indicators-all.js");
      // Advanced annotations (Fibonacci, pitchfork, parallel channel, Elliott
      // waves, etc.). NOT annotations.js — that only provides basic shapes.
      await import("highcharts/esm/modules/annotations-advanced.js");
      // Drag-panes: lets the user resize the volume/RSI sub-panes by dragging.
      await import("highcharts/esm/modules/drag-panes.js");
      // Price indicator: the "current price" dashed line + label button in the
      // stock-tools GUI ("currentPriceIndicator").
      await import("highcharts/esm/modules/price-indicator.js");
      // Full-screen: the "fullScreen" button in the stock-tools GUI.
      await import("highcharts/esm/modules/full-screen.js");
      // Stock-tools GUI itself — must be last, depends on all modules above.
      await import("highcharts/esm/modules/stock-tools.js");
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      // Make advanced drawn annotations (Fibonacci, pitchfork, measure, …)
      // selectable so their edit/delete toolbar opens on click. See the helper.
      ensureAnnotationsSelectable(Highcharts);
      const colors = chartColors();
      colorsRef.current = colors;
      Highcharts.setOptions(highchartsTheme(colors));
      const chart = Highcharts.stockChart(
        containerRef.current,
        buildStockOptions({
          symbol,
          bars: barsRef.current,
          type: INITIAL_TYPE,
          scale: { log: false, pct: false },
          showVolume: SHOW_VOLUME,
          sma20: false,
          compares: [],
          colors,
          selectedRangeIndex: rangeButtonIndexForPreset(initialRangeRef.current),
          onRangeButtonClick: (preset) => {
            // Recompute the High/Low markers for the newly selected window.
            // afterSetExtremes fires AFTER the extremes are applied, so the
            // visible range is already current here.
            refreshHighLowAnnotation(chartRef.current, barsRef.current, colorsRef.current);
            // Ignore the first (on-mount) emission from applying the initial
            // rangeSelector selection; forward all later user clicks.
            if (!mountedRef.current) {
              mountedRef.current = true;
              return;
            }
            onRangeChangeRef.current(preset);
          },
        }),
      );
      if (disposed) {
        chart.destroy();
        return;
      }
      chartRef.current = chart;
      // Initial High/Low marker (no-op until bars arrive; the bars effect below
      // refreshes once data populates).
      refreshHighLowAnnotation(chart, barsRef.current, colors);
    })();
    const observer = new ResizeObserver(() => chartRef.current?.reflow());
    observer.observe(el);
    return () => {
      disposed = true;
      observer.disconnect();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
    // Create once: symbol/bars changes are applied surgically below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Surgical bars/symbol update (preserves drawings) ──────────────────────
  useEffect(() => {
    barsRef.current = bars;
    const chart = chartRef.current;
    if (!chart) return;
    const price = chart.get(STOCK_PRICE_ID) as Series | undefined;
    if (price && "setData" in price) {
      // Partial update: only the display name. Cast because Highcharts types a
      // series update as the full discriminated SeriesOptionsType union.
      price.update({ name: symbol } as Parameters<Series["update"]>[0], false);
      // Shape the data for the series type the user may have switched to via the
      // stock-tools `typeChange` GUI button — NOT the create-time constant.
      // Feeding candle-shaped points into a line/area series (or vice versa)
      // corrupts the points; derive the shape from the live series type.
      price.setData(toMainSeriesData(bars, stockTypeFromSeries(price.type)), false);
    }
    const vol = chart.get(STOCK_VOLUME_ID) as Series | undefined;
    if (vol && "setData" in vol) {
      vol.setData(toVolumeSeriesData(bars), false);
    }
    chart.redraw(false);
    refreshHighLowAnnotation(chart, bars, colorsRef.current);
  }, [symbol, bars]);

  // ── Live ticks (coalesced via rAF) ────────────────────────────────────────
  useEffect(() => {
    if (!symbol) return;

    const flush = () => {
      rafRef.current = null;
      const pending = pendingTickRef.current;
      pendingTickRef.current = null;
      if (!pending || !chartRef.current) return;
      // Match the point shape to the series type the user may have switched to
      // via the stock-tools GUI, not the create-time constant.
      const priceSeries = chartRef.current.get(STOCK_PRICE_ID) as Series | undefined;
      applyTickToStockChart({
        chart: chartRef.current,
        bar: pending.bar,
        appended: pending.appended,
        type: stockTypeFromSeries(priceSeries?.type),
        showVolume: SHOW_VOLUME,
        redraw: true,
      });
    };

    const unsubscribe = subscribeTicks(symbol, (tick) => {
      const timeMs = parseTickTimeMs(tick.time);
      const { bars: next, appended } = mergeTickIntoBars(barsRef.current, {
        price: tick.price,
        size: tick.size,
        timeMs,
      });
      if (!next.length) return;
      barsRef.current = next;
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
  }, [symbol]);

  // ── Feed status badge ─────────────────────────────────────────────────────
  useEffect(() => onFeedStatus(setFeed), []);

  // ── Compare: auto-percent so series align; revert when last is removed ─────
  function applyCompareMode(entries: CompareEntry[]): void {
    const chart = chartRef.current;
    if (!chart) return;
    const count = entries.length;
    // Percent-rebased curves must all start on the same date. Highstock
    // rebases each series at its own first point in range, so a compare whose
    // history begins later would start at 0% on a different day. Floor the
    // axis at the latest inception across the main series and every loaded
    // compare; lift the floor when the last compare is removed.
    const firsts = [
      barsRef.current[0]?.t,
      ...entries.map((entry) => entry.bars[0]?.t),
    ].filter((t): t is number => typeof t === "number");
    const commonStart = count > 0 && firsts.length > 0 ? Math.max(...firsts) : null;
    chart.update(
      {
        plotOptions: { series: { compare: count > 0 ? "percent" : undefined } },
        xAxis: { min: commonStart },
      },
      true,
    );
  }

  async function addCompare(item: SymbolSearchResult): Promise<void> {
    const chart = chartRef.current;
    if (!chart) return;
    const key = compareKey(item);
    const existing = comparesRef.current;
    if (existing.some((c) => c.key === key) || existing.length >= MAX_COMPARE) return;
    const label = item.symbol.toUpperCase();
    const entry: CompareEntry = { key, label, bars: [] };
    setCompares((current) => [...current, entry]);

    let loaded: HistoryBar[] = [];
    try {
      const history = await fetchStockHistory(item.symbol, 2520);
      loaded = history.bars ?? [];
    } catch {
      // Drop the chip if the history fetch fails; nothing to plot.
      setCompares((current) => current.filter((c) => c.key !== key));
      return;
    }
    const live = chartRef.current;
    // Bail if the chart was destroyed or the chip removed while loading.
    if (!live || !comparesRef.current.some((c) => c.key === key)) return;
    const colors = chartColors();
    const index = comparesRef.current.findIndex((c) => c.key === key);
    live.addSeries(
      {
        id: `compare-${key}`,
        type: "line",
        name: label,
        data: toMainSeriesData(loaded, "line"),
        yAxis: "price-axis",
        color: colors.categories[(Math.max(index, 0) + 4) % colors.categories.length],
        lineWidth: 1.4,
        marker: { enabled: false },
      },
      false,
    );
    const nextEntries = comparesRef.current.map((c) =>
      c.key === key ? { ...c, bars: loaded } : c,
    );
    setCompares(nextEntries);
    applyCompareMode(nextEntries);
  }

  function removeCompare(key: string): void {
    const chart = chartRef.current;
    chart?.get(`compare-${key}`)?.remove(false);
    const remaining = comparesRef.current.filter((c) => c.key !== key);
    setCompares(remaining);
    applyCompareMode(remaining);
  }

  // ── Log/Linear toggle (native GUI has none) ───────────────────────────────
  const [log, setLog] = useState(false);
  function toggleLog(): void {
    const next = !log;
    setLog(next);
    const axis = chartRef.current?.get("price-axis") as
      | { update?: (o: YAxisOptions, redraw?: boolean) => void }
      | undefined;
    axis?.update?.({ type: next ? "logarithmic" : "linear" }, true);
  }

  const showEmpty = !!emptyMessage && !!isEmpty;
  const badge = FEED_BADGE[feed];

  return (
    <div className={`highcharts-bindings-container flex flex-col ${className ?? ""}`}>
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <SymbolSearchInput active={null} onSelect={(item) => void addCompare(item)} />
        <div className="flex flex-wrap items-center gap-1">
          {compares.map((compare) => (
            <button
              key={compare.key}
              type="button"
              className="h-7 border border-border-strong bg-field px-2 text-[11px] text-text-secondary hover:bg-layer-hover hover:text-text-primary"
              onClick={() => removeCompare(compare.key)}
              aria-label={`Remove comparison ${compare.label}`}
            >
              {compare.label} x
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={log}
          onClick={toggleLog}
          className={`h-7 border border-border-strong px-2 text-[11px] transition-colors ${
            log
              ? "bg-accent font-bold text-on-accent"
              : "bg-field text-text-muted hover:bg-layer-hover hover:text-text-primary"
          }`}
        >
          Log
        </button>
        <span
          className={`ml-auto inline-flex items-center gap-1 text-[11px] font-bold ${
            badge.live ? "text-gain" : "text-text-muted"
          }`}
          aria-label={`Feed status: ${badge.label}`}
        >
          <span
            aria-hidden
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              badge.live ? "bg-gain" : "bg-text-muted"
            }`}
          />
          {badge.label}
        </span>
      </div>
      <div className="relative min-h-0 flex-1 bg-surface-1">
        <div ref={containerRef} className="h-full w-full" />
        {showEmpty && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[13px] text-text-muted">
            {emptyMessage}
          </div>
        )}
      </div>
    </div>
  );
}
