"use client";

/**
 * Thin Highcharts Grid Pro wrapper: create in a ref on mount, update on option
 * change, destroy on unmount. The grid lib is dynamically imported so it never
 * runs during SSR. All grid content comes from the pure adapter in
 * `src/lib/grid/gridOptions.ts`. Mirrors the EChart wrapper.
 */
import { useEffect, useRef } from "react";
import type { Grid, Options } from "@highcharts/grid-pro";

import { gridRowCount } from "@/lib/grid/gridEmpty";
import "@highcharts/grid-pro/css/grid-pro.css";
import "@/lib/grid/grid-theme.css";

export function DataGrid({
  options,
  className,
  emptyMessage,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<Grid | null>(null);
  // Keep the freshest options for the async create callback without re-running it.
  const latestOptions = useRef(options);
  latestOptions.current = options;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void import("@highcharts/grid-pro").then(({ grid }) => {
      if (disposed || !containerRef.current) return;
      gridRef.current = grid(containerRef.current, latestOptions.current);
    });
    return () => {
      disposed = true;
      gridRef.current?.destroy();
      gridRef.current = null;
    };
  }, []);

  useEffect(() => {
    void gridRef.current?.update(options);
  }, [options]);

  const showEmpty = !!emptyMessage && gridRowCount(options) === 0;

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
