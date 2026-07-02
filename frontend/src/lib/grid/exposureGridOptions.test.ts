import { describe, expect, it } from "vitest";

import { GRAPHITE_THEME } from "./gridOptions";
import { exposureGridOptions, type ExposureGridRow } from "./exposureGridOptions";

const ROWS: ExposureGridRow[] = [
  { id: "asset|equity", label: "Equity <Core>", kind: "Asset Class", pct: 64.25 },
  { id: "asset|fixed", label: "Fixed Income", kind: "Asset Class", pct: 30.5 },
];

type CellLike = {
  value: unknown;
  row: { getCell: (id: string) => { value: unknown } | undefined };
};

function fmtCall(
  formatter: unknown,
  value: unknown,
  rowValues: Record<string, unknown>,
): string {
  return (formatter as (this: CellLike) => string).call({
    value,
    row: {
      getCell: (id: string) => (id in rowValues ? { value: rowValues[id] } : undefined),
    },
  });
}

describe("exposureGridOptions", () => {
  it("builds the two visible exposure columns plus hidden sync fields", () => {
    const opts = exposureGridOptions(ROWS, "asset|equity");
    const data = opts.data as { columns: Record<string, unknown[]> };

    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(data.columns.label).toEqual(["Equity <Core>", "Fixed Income"]);
    expect(data.columns.pct).toEqual([64.25, 30.5]);
    expect(data.columns.id).toEqual(["asset|equity", "asset|fixed"]);
    expect(data.columns.kind).toEqual(["Asset Class", "Asset Class"]);

    const columns = opts.columns ?? [];
    expect(columns.map((column) => column.id)).toEqual(["label", "pct", "id", "kind"]);
    expect(columns.find((column) => column.id === "id")?.enabled).toBe(false);
    expect(columns.find((column) => column.id === "kind")?.enabled).toBe(false);
  });

  it("enables column sorting like the rest of the product's grids", () => {
    const opts = exposureGridOptions(ROWS, "asset|equity");
    expect(opts.columnDefaults?.sorting?.enabled).toBe(true);
  });

  it("renders escaped hover targets and marks the active row", () => {
    const opts = exposureGridOptions(ROWS, "asset|equity");
    const labelFormatter = opts.columns?.find((column) => column.id === "label")?.cells?.formatter;
    const pctFormatter = opts.columns?.find((column) => column.id === "pct")?.cells?.formatter;

    expect(
      fmtCall(labelFormatter, "Equity <Core>", {
        id: "asset|equity",
        kind: "Asset Class",
      }),
    ).toContain("ix-grid-active");
    expect(
      fmtCall(labelFormatter, "Equity <Core>", {
        id: "asset|equity",
        kind: "Asset Class",
      }),
    ).toContain("Equity &lt;Core&gt;");
    expect(fmtCall(pctFormatter, 64.25, { id: "asset|equity" })).toContain(
      "64.25%",
    );
  });
});
