"use client";

/**
 * Thin Highcharts Stock wrapper: dynamically import highcharts/highstock
 * (never SSR), apply the Graphite theme globally, create a stockChart once,
 * update() on option change, reflow() on resize, destroy() on unmount.
 * `onReady` exposes the live Chart so consumers can stream live ticks via
 * `chart.series[i].addPoint(...)` (P2). Mirrors HighchartsChart.
 */
import { useEffect, useRef } from "react";
import type { Chart, Options } from "highcharts";

import { chartColors } from "@/lib/charts/chartColors";
import { highchartsTheme } from "@/lib/charts/hc/theme";

export function HighchartsStockChart({
  options,
  className,
  emptyMessage,
  isEmpty,
  onReady,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
  isEmpty?: boolean;
  onReady?: (chart: Chart) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const latestOptions = useRef(options);
  latestOptions.current = options;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void (async () => {
      // Use the ESM build so Stock modules register on the same Highcharts
      // singleton. The UMD module paths do not self-register under Turbopack.
      const mod = await import("highcharts/esm/highstock.js");
      await import("highcharts/esm/indicators/indicators.js");
      await import("highcharts/esm/indicators/rsi.js");
      await import("highcharts/esm/modules/annotations.js");
      await import("highcharts/esm/modules/stock-tools.js");
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      Highcharts.setOptions(highchartsTheme(chartColors()));
      const chart = Highcharts.stockChart(containerRef.current, latestOptions.current);
      if (disposed) {
        chart.destroy();
        return;
      }
      chartRef.current = chart;
      onReadyRef.current?.(chart);
    })();
    const observer = new ResizeObserver(() => chartRef.current?.reflow());
    observer.observe(el);
    return () => {
      disposed = true;
      observer.disconnect();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // animation=false: skip the 350ms theme animation on reactive updates
    // (range switches redraw thousands of SVG paths → freeze/blank). The
    // initial Highcharts.stockChart() above keeps its entry animation.
    chart.update(options, true, true, false);
    onReadyRef.current?.(chart);
  }, [options]);

  const showEmpty = !!emptyMessage && !!isEmpty;

  return (
    <div className={`relative ${className ?? ""}`}>
      <div ref={containerRef} className="h-full w-full" />
      {showEmpty && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[13px] text-text-muted">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}
