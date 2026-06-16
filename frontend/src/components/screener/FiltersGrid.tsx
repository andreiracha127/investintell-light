"use client";

import { useMemo } from "react";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { DataGrid } from "@/components/ui/DataGrid";
import { screenFiltersToGridOptions, type FiltersGridCallbacks } from "@/lib/grid/filtersGridOptions";

export function FiltersGrid({
  filters,
  catalog,
  builds,
  selectedForDelete,
  callbacks,
  className,
}: {
  filters: ScreenFilter[];
  catalog: Map<string, MetricDef>;
  builds: Map<string, MetricBuild>;
  selectedForDelete: ReadonlySet<string>;
  callbacks: FiltersGridCallbacks;
  className?: string;
}) {
  const options = useMemo(
    () => screenFiltersToGridOptions(filters, catalog, builds, selectedForDelete, callbacks),
    [filters, catalog, builds, selectedForDelete, callbacks],
  );
  return <DataGrid options={options} className={className} />;
}
