import { describe, it, expect } from "vitest";

import { sparklineSvg } from "./sparkline";

const dist = { bin_edges: [0, 10, 20, 30], counts: [1, 4, 2], counts_normalized: [0.25, 1, 0.5] };

describe("sparklineSvg", () => {
  it("renders one rect per bin", () => {
    const svg = sparklineSvg(dist, { min: null, max: null });
    expect((svg.match(/<rect/g) ?? []).length).toBe(3);
  });
  it("marks bins overlapping the [min,max] band as selected", () => {
    const svg = sparklineSvg(dist, { min: null, max: 15 }); // [0,10) and [10,20) overlap
    expect((svg.match(/ix-spark-on/g) ?? []).length).toBe(2);
  });
  it("returns an empty string for an empty distribution", () => {
    expect(
      sparklineSvg({ bin_edges: [], counts_normalized: [] }, { min: null, max: null }),
    ).toBe("");
  });
});
