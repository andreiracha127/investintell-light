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
      const mod = await import("highcharts/esm/highstock.js");
      await import("highcharts/esm/highcharts-more.js");
      // Native indicators (RSI/MACD/Bollinger/…) the user adds via the GUI.
      await import("highcharts/esm/indicators/indicators-all.js");
      await import("highcharts/esm/modules/annotations.js");
      await import("highcharts/esm/modules/stock-tools.js");
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      const colors = chartColors();
      Highcharts.setOptions(highchartsTheme(colors));
      const chart = Highcharts.stockChart(
        containerRef.current,
        buildStockOptions({
          symbol,
          bars: barsRef.current,
          type: INITIAL_TYPE,
          scale: { log: false, pct: false },
          showVolume: SHOW_VOLUME,
          sma20: true,
          compares: [],
          colors,
          selectedRangeIndex: rangeButtonIndexForPreset(initialRangeRef.current),
          onRangeButtonClick: (preset) => {
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
      price.setData(toMainSeriesData(bars, INITIAL_TYPE), false);
    }
    const vol = chart.get(STOCK_VOLUME_ID) as Series | undefined;
    if (vol && "setData" in vol) {
      vol.setData(toVolumeSeriesData(bars), false);
    }
    chart.redraw(false);
  }, [symbol, bars]);

  // ── Live ticks (coalesced via rAF) ────────────────────────────────────────
  useEffect(() => {
    if (!symbol) return;

    const flush = () => {
      rafRef.current = null;
      const pending = pendingTickRef.current;
      pendingTickRef.current = null;
      if (!pending || !chartRef.current) return;
      applyTickToStockChart({
        chart: chartRef.current,
        bar: pending.bar,
        appended: pending.appended,
        type: INITIAL_TYPE,
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
  function applyCompareMode(count: number): void {
    const chart = chartRef.current;
    if (!chart) return;
    chart.update(
      { plotOptions: { series: { compare: count > 0 ? "percent" : undefined } } },
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
    setCompares((current) =>
      current.map((c) => (c.key === key ? { ...c, bars: loaded } : c)),
    );
    applyCompareMode(comparesRef.current.length);
  }

  function removeCompare(key: string): void {
    const chart = chartRef.current;
    chart?.get(`compare-${key}`)?.remove(false);
    const remaining = comparesRef.current.filter((c) => c.key !== key);
    setCompares(remaining);
    applyCompareMode(remaining.length);
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
    <div className={`flex flex-col ${className ?? ""}`}>
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
      <div className="relative flex-1">
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
