import { describe, expect, it } from "vitest";

import { verticalFill, withAlpha } from "@/lib/charts/hc/gradient";

describe("withAlpha", () => {
  it("converts #rrggbb to rgba", () => {
    expect(withAlpha("#0f62fe", 0.5)).toBe("rgba(15, 98, 254, 0.5)");
  });

  it("expands #rgb shorthand", () => {
    expect(withAlpha("#08f", 1)).toBe("rgba(0, 136, 255, 1)");
  });

  it("passes through non-hex colors untouched", () => {
    expect(withAlpha("rgba(1,2,3,1)", 0.5)).toBe("rgba(1,2,3,1)");
  });
});

describe("verticalFill", () => {
  it("builds a top-to-bottom linear gradient with alpha stops", () => {
    const fill = verticalFill("#0f62fe", 0.9, 0.2);
    expect(fill.linearGradient).toEqual({ x1: 0, y1: 0, x2: 0, y2: 1 });
    expect(fill.stops[0]).toEqual([0, "rgba(15, 98, 254, 0.9)"]);
    expect(fill.stops[1]).toEqual([1, "rgba(15, 98, 254, 0.2)"]);
  });
});
