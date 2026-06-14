import { describe, expect, it } from "vitest";

import type { Options } from "@highcharts/grid-pro";

import { gridRowCount } from "./gridEmpty";

describe("gridRowCount", () => {
  it("returns 0 when data is absent", () => {
    expect(gridRowCount({} as Options)).toBe(0);
  });

  it("returns 0 when the columns object is empty", () => {
    const options = {
      data: { providerType: "local", columns: {} },
    } as unknown as Options;
    expect(gridRowCount(options)).toBe(0);
  });

  it("returns 0 when the first column has no rows", () => {
    const options = {
      data: { providerType: "local", columns: { ticker: [] } },
    } as unknown as Options;
    expect(gridRowCount(options)).toBe(0);
  });

  it("returns N for a column with N rows", () => {
    const options = {
      data: {
        providerType: "local",
        columns: { ticker: ["AAA", "BBB", "CCC"], sharpe_1y: [1.2, null, 0.3] },
      },
    } as unknown as Options;
    expect(gridRowCount(options)).toBe(3);
  });
});
