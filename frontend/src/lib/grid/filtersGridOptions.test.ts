import { describe, it, expect } from "vitest";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { screenFiltersToGridOptions, filtersGridData } from "./filtersGridOptions";

const PE: MetricDef = {
  code: "pe_ratio",
  name: "Price / Earnings (TTM)",
  abbreviation: "P/E",
  category: "Fundamentals: Valuation",
  sub_category: "Multiples",
  data_type: "float",
  scale_note: "",
  presets: [],
};
const ROE: MetricDef = {
  ...PE,
  code: "roe",
  name: "Return on Equity",
  abbreviation: "ROE",
  data_type: "percent",
};
const catalog = new Map<string, MetricDef>([
  ["pe_ratio", PE],
  ["roe", ROE],
]);
const filters: ScreenFilter[] = [
  { metric_code: "pe_ratio", min_value: null, max_value: 25, position: 0 },
  { metric_code: "roe", min_value: 0.15, max_value: null, position: 1 },
];
const builds = new Map<string, MetricBuild>([
  [
    "pe_ratio",
    {
      metric_code: "pe_ratio",
      available_count: 100,
      distribution: { bin_edges: [0, 12, 25], counts: [3, 1], counts_normalized: [1, 0.3] },
    },
  ],
  ["roe", { metric_code: "roe", available_count: 100, distribution: null }],
]);

const noop: import("./filtersGridOptions").FiltersGridCallbacks = {
  onEditBound() {},
  onRemove() {},
  onMove() {},
  onToggleSelect() {},
  onSelectRow() {},
};

describe("filtersGridData", () => {
  it("scales percent bounds to 0-100 for display", () => {
    const data = filtersGridData(filters, catalog, builds, new Set());
    const cols = data.columns as Record<string, Array<number | null>>;
    expect(cols.min[1]).toBe(15); // roe 0.15 -> 15
    expect(cols.max[0]).toBe(25); // pe_ratio raw
  });
  it("marks selected rows in the __select column", () => {
    const data = filtersGridData(filters, catalog, builds, new Set(["roe"]));
    const cols = data.columns as Record<string, boolean[]>;
    expect(cols.__select).toEqual([false, true]);
  });
});

describe("screenFiltersToGridOptions", () => {
  it("emits a column per control + hidden metric_code", () => {
    const opts = screenFiltersToGridOptions(filters, catalog, builds, new Set(), noop);
    const ids = (opts.columns ?? []).map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "__select",
        "__up",
        "__down",
        "metric",
        "min",
        "max",
        "dist",
        "__remove",
        "metric_code",
      ]),
    );
  });

  it("declares data types for control and rendered columns", () => {
    const opts = screenFiltersToGridOptions(filters, catalog, builds, new Set(), noop);
    const columns = new Map((opts.columns ?? []).map((column) => [column.id, column]));

    expect(columns.get("__select")?.dataType).toBe("boolean");
    expect(columns.get("__up")?.dataType).toBe("string");
    expect(columns.get("__down")?.dataType).toBe("string");
    expect(columns.get("dist")?.dataType).toBe("string");
    expect(columns.get("__remove")?.dataType).toBe("string");
    expect(columns.get("metric_code")?.dataType).toBe("string");
    expect(columns.get("is_percent")?.dataType).toBe("boolean");
  });
});
