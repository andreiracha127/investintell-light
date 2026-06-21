import { describe, it, expect } from "vitest";

import { buildHcMacroBandsOption } from "./macro-bands";
import { TEST_COLORS } from "./__fixtures__/colors";

describe("buildHcMacroBandsOption", () => {
  it("returns null for empty bands", () => {
    expect(buildHcMacroBandsOption([], TEST_COLORS)).toBeNull();
  });

  it("emits one range per class with min/max extent", () => {
    const opt = buildHcMacroBandsOption(
      [
        { asset_class: "equity", min_weight: 0.4, max_weight: 0.64 },
        { asset_class: "cash", min_weight: 0.03, max_weight: 0.105 },
      ],
      TEST_COLORS,
    )!;
    const data = (opt.series?.[0] as { data: unknown[] }).data;
    expect(data).toHaveLength(2);
    expect(data[0]).toEqual(expect.arrayContaining([0.4, 0.64]));
  });

  it("orders classes equity, fixed_income, alternatives, cash", () => {
    const opt = buildHcMacroBandsOption(
      [
        { asset_class: "cash", min_weight: 0, max_weight: 0.1 },
        { asset_class: "equity", min_weight: 0.4, max_weight: 0.6 },
      ],
      TEST_COLORS,
    )!;
    const cats = (opt.xAxis as { categories: string[] }).categories;
    expect(cats.indexOf("equity")).toBeLessThan(cats.indexOf("cash"));
  });
});
