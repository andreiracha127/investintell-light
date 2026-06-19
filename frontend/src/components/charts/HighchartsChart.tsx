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

import { chartColors } from "@/lib/charts/chartColors";
import { highchartsTheme } from "@/lib/charts/hc/theme";

type StockUiOptions = Options & {
  rangeSelector?: { enabled?: boolean };
  navigator?: { enabled?: boolean };
  scrollbar?: { enabled?: boolean };
  stockTools?: { gui?: { enabled?: boolean } };
  navigation?: { bindingsClassName?: string };
};

function coreOnlyOptions(options: Options): Options {
  return {
    ...(options as StockUiOptions),
    rangeSelector: { ...(options as StockUiOptions).rangeSelector, enabled: false },
    navigator: { ...(options as StockUiOptions).navigator, enabled: false },
    scrollbar: { ...(options as StockUiOptions).scrollbar, enabled: false },
    stockTools: {
      ...(options as StockUiOptions).stockTools,
      gui: {
        ...(options as StockUiOptions).stockTools?.gui,
        enabled: false,
      },
    },
    navigation: { ...(options as StockUiOptions).navigation, bindingsClassName: undefined },
  } as Options;
}

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
    void (async () => {
      // Use the ESM build so the Core modules below register on the SAME
      // Highcharts instance (the UMD `highcharts/modules/*` bundles expect a
      // global and do not self-register under ESM).
      const mod = await import("highcharts/esm/highcharts.js");
      // Register Core modules consumed by hc/* builders before any chart is
      // created: heatmap (also provides colorAxis, used by correlation +
      // monthly-returns), xrange (regime strip), highcharts-more (arearange
      // confidence cones), and annotations (macro RRG).
      await import("highcharts/esm/modules/heatmap.js");
      await import("highcharts/esm/modules/xrange.js");
      await import("highcharts/esm/highcharts-more.js");
      await import("highcharts/esm/modules/annotations.js");
      // treemap: portfolio look-through exposure tiles. highcharts-more (above)
      // provides the `packedbubble` series used by the Performance contributors.
      await import("highcharts/esm/modules/treemap.js");
      await import("highcharts/esm/modules/sunburst.js");
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      // Apply the token-driven Graphite theme globally before creating.
      Highcharts.setOptions(highchartsTheme(chartColors()));
      const chart = Highcharts.chart(containerRef.current, coreOnlyOptions(latestOptions.current));
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
    // redraw + oneToOne: replace series/axes rather than merge-append.
    // animation=false: skip the 350ms theme animation on reactive updates
    // (range switches redraw thousands of SVG paths → freeze/blank). The
    // initial Highcharts.chart() above keeps its entry animation.
    chart.update(coreOnlyOptions(options), true, true, false);
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
