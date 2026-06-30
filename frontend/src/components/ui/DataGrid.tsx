"use client";

/**
 * Thin Highcharts Grid Pro wrapper: create in a ref on mount, update on option
 * change, destroy on unmount. The grid lib is dynamically imported so it never
 * runs during SSR. All grid content comes from the pure adapter in
 * `src/lib/grid/gridOptions.ts`. Mirrors the Highcharts wrapper pattern.
 */
import { useEffect, useRef, useState } from "react";
import type { Grid, Options } from "@highcharts/grid-pro";

import { gridRowCount } from "@/lib/grid/gridEmpty";
import "@highcharts/grid-pro/css/grid-pro.css";
import "@/lib/grid/grid-theme.css";

type GridKeyOptions = Options & { gridKey?: string };

/**
 * Force-disable the Highcharts Grid credits badge on every grid, mirroring the
 * charts' `theme.ts` which already sets `credits.enabled = false`. Applied at
 * the single wrapper so individual grid adapters don't each repeat it.
 */
function withGridChrome(options: Options): Options {
  const gridKey = process.env.NEXT_PUBLIC_HIGHCHARTS_GRID_LICENSE_KEY?.trim();
  const current = options as GridKeyOptions;
  return {
    ...options,
    gridKey: current.gridKey ?? (gridKey || undefined),
    credits: { enabled: false },
  } as GridKeyOptions;
}

export function DataGrid({
  options,
  className,
  emptyMessage,
  onReady,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
  /**
   * Called with the live Grid instance once `viewport` (and thus
   * `viewport.tbodyElement`) is ready — after the initial async create AND
   * after every `update()`. Consumers (e.g. infinite scroll) use it to attach
   * a listener to the body scroll container; the handler must be idempotent
   * (detach any previous listener before attaching a new one) because the
   * viewport/tbody may be rebuilt by `update()`.
   */
  onReady?: (grid: Grid) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<Grid | null>(null);
  const [isReady, setIsReady] = useState(false);
  // Keep the freshest options for the async create callback without re-running it.
  const latestOptions = useRef(options);
  latestOptions.current = options;
  // Hold onReady in a ref so changing its identity never re-runs the create
  // effect (which would destroy/recreate the grid).
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  // Fire onReady only once `viewport.tbodyElement` exists. Guards every access.
  const notifyReady = (grid: Grid | null) => {
    if (grid?.viewport?.tbodyElement) onReadyRef.current?.(grid);
  };

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    setIsReady(false);
    // Async factory overload: resolves AFTER load, so viewport is ready.
    void import("@highcharts/grid-pro").then(({ grid }) => {
      if (disposed || !containerRef.current) return;
      void grid(containerRef.current, withGridChrome(latestOptions.current), true).then((g) => {
        if (disposed) {
          g.destroy();
          return;
        }
        gridRef.current = g;
        setIsReady(true);
        notifyReady(g);
      });
    });
    return () => {
      disposed = true;
      gridRef.current?.destroy();
      gridRef.current = null;
    };
  }, []);

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    // update() may rebuild the viewport/tbody; re-notify once it settles so the
    // consumer can rebind its scroll listener to the fresh tbodyElement.
    void grid.update(withGridChrome(options)).then(() => notifyReady(grid));
  }, [options]);

  const showEmpty = !!emptyMessage && gridRowCount(options) === 0;

  return (
    <div className={`relative ${className ?? ""}`}>
      <div ref={containerRef} className="h-full w-full" />
      {!isReady && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 animate-pulse bg-layer-active"
        />
      )}
      {showEmpty && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[13px] text-text-muted">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}
