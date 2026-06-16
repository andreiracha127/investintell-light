import { describe, it, expect } from "vitest";

import { toDisplayText, parseBound } from "./bounds";

describe("toDisplayText", () => {
  it("renders null as an empty string", () => expect(toDisplayText(null, false)).toBe(""));
  it("scales percent fractions to 0-100", () => expect(toDisplayText(0.05, true)).toBe("5"));
  it("passes non-percent values through", () => expect(toDisplayText(25, false)).toBe("25"));
});

describe("parseBound", () => {
  it("treats blank as unbounded (null)", () => expect(parseBound("  ", false)).toBeNull());
  it("returns undefined for invalid input", () => expect(parseBound("abc", false)).toBeUndefined());
  it("converts percent input to a fraction", () => expect(parseBound("5", true)).toBe(0.05));
  it("keeps raw values for non-percent", () => expect(parseBound("25", false)).toBe(25));
});
