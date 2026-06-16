import { describe, expect, it } from "vitest";

import {
  defaultUniverseDraft,
  objectivesForBroad,
  resolveObjectiveForBroad,
  universeDraftToSpec,
} from "./assets";

describe("universeDraftToSpec", () => {
  it("ranked mode: broad_universe false, max_positions mirrors max_assets, keeps include ids", () => {
    const draft = { ...defaultUniverseDraft(), maxAssets: 20 };
    const spec = universeDraftToSpec(draft, ["a", "b"]);
    expect(spec.broad_universe).toBe(false);
    expect(spec.max_assets).toBe(20);
    expect(spec.max_positions).toBe(20);
    expect(spec.min_pair_overlap).toBe(252);
    expect(spec.include_instrument_ids).toEqual(["a", "b"]);
  });

  it("broad mode: broad_universe true, max_positions from maxPositions, omits include ids", () => {
    const draft = {
      ...defaultUniverseDraft(),
      broadUniverse: true,
      maxPositions: 25,
      maxAssets: 40,
    };
    const spec = universeDraftToSpec(draft, ["a", "b"]);
    expect(spec.broad_universe).toBe(true);
    expect(spec.max_positions).toBe(25);
    expect("include_instrument_ids" in spec).toBe(false);
  });

  it("default draft is ranked with maxPositions 30", () => {
    const draft = defaultUniverseDraft();
    expect(draft.broadUniverse).toBe(false);
    expect(draft.maxPositions).toBe(30);
  });
});

describe("objective gating for broad mode", () => {
  it("ranked mode keeps every objective including bl_utility", () => {
    const values = objectivesForBroad(false).map((o) => o.value);
    expect(values).toContain("bl_utility");
    expect(values).toContain("min_cvar");
  });

  it("broad mode drops the mu-based bl_utility objective", () => {
    const values = objectivesForBroad(true).map((o) => o.value);
    expect(values).not.toContain("bl_utility");
    expect(values).toContain("min_cvar");
  });

  it("resolveObjectiveForBroad falls bl_utility back to min_cvar only in broad mode", () => {
    expect(resolveObjectiveForBroad("bl_utility", true)).toBe("min_cvar");
    expect(resolveObjectiveForBroad("bl_utility", false)).toBe("bl_utility");
    expect(resolveObjectiveForBroad("min_vol", true)).toBe("min_vol");
  });
});
