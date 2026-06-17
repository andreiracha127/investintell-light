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
  it("ranked mode keeps every objective including the scenario/mu-based ones", () => {
    const values = objectivesForBroad(false).map((o) => o.value);
    expect(values).toContain("bl_utility");
    expect(values).toContain("min_cvar");
  });

  it("broad mode keeps ONLY covariance-based objectives", () => {
    // min_cvar (scenario) needs joint scenario rows and 422s when the diverse
    // broad universe lacks a common window; bl_utility (mu) is gate-G5 blocked.
    // Broad runs on a pairwise covariance, so only covariance objectives apply.
    const values = objectivesForBroad(true).map((o) => o.value);
    expect(values).not.toContain("min_cvar");
    expect(values).not.toContain("bl_utility");
    expect(values).toEqual([
      "min_vol",
      "erc",
      "max_diversification",
      "equal_weight",
    ]);
  });

  it("resolveObjectiveForBroad steers non-covariance objectives to min_vol in broad mode", () => {
    expect(resolveObjectiveForBroad("min_cvar", true)).toBe("min_vol");
    expect(resolveObjectiveForBroad("bl_utility", true)).toBe("min_vol");
    // Covariance objectives are left untouched in broad mode.
    expect(resolveObjectiveForBroad("erc", true)).toBe("erc");
    expect(resolveObjectiveForBroad("equal_weight", true)).toBe("equal_weight");
    // Ranked mode never rewrites the objective.
    expect(resolveObjectiveForBroad("min_cvar", false)).toBe("min_cvar");
    expect(resolveObjectiveForBroad("bl_utility", false)).toBe("bl_utility");
  });
});
