"use client";

/**
 * Thin Highcharts Core wrapper: dynamically import highcharts (never SSR),
 * apply the Graphite theme globally, create the chart once into a ref,
 * update() on option change, reflow() on resize, destroy() on unmount.
 * Mirrors DataGrid.tsx. Chart content comes from pure builders in
 * `src/lib/charts/hc/*`.
 */
import { useEffect, useRef } from "react";
import type { Chart, Options } from "highcharts";

import { chartColors } from "@/lib/charts/theme";
import { highchartsTheme } from "@/lib/charts/hc/theme";

export function HighchartsChart({
  options,
  className,
  emptyMessage,
  isEmpty,
  onReady,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
  /** Consumer-decided empty state (Highcharts has no generic row count). */
  isEmpty?: boolean;
  onReady?: (chart: Chart) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  // Freshest options/callback for the async create, without re-running it.
  const latestOptions = useRef(options);
  latestOptions.current = options;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void import("highcharts").then((mod) => {
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      // Apply the token-driven Graphite theme globally before creating.
      Highcharts.setOptions(highchartsTheme(chartColors()));
      const chart = Highcharts.chart(containerRef.current, latestOptions.current);
      if (disposed) {
        chart.destroy();
        return;
      }
      chartRef.current = chart;
      onReadyRef.current?.(chart);
    });
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
    // redraw + oneToOne: replace series/axes rather than merge-append.
    chart.update(options, true, true);
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
