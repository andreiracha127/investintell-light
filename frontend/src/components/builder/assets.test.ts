// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({}));

import {
  defaultUniverseDraft,
  OBJECTIVES,
  MANDATE_CVAR_PRESETS,
  objectivesForBroad,
  resolveObjectiveForBroad,
  universeDraftToSpec,
  type Mandate,
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

describe("max_return_cvar objective entry", () => {
  it("is the FIRST objective (the default) and is labelled + described", () => {
    const first = OBJECTIVES[0];
    expect(first.value).toBe("max_return_cvar");
    expect(first.label.length).toBeGreaterThan(0);
    expect(first.description.length).toBeGreaterThan(0);
  });

  it("ranked mode still exposes max_return_cvar", () => {
    const values = objectivesForBroad(false).map((o) => o.value);
    expect(values).toContain("max_return_cvar");
  });

  it("broad mode EXCLUDES max_return_cvar (covariance objectives only)", () => {
    const values = objectivesForBroad(true).map((o) => o.value);
    expect(values).not.toContain("max_return_cvar");
    expect(values).toEqual([
      "min_vol",
      "erc",
      "max_diversification",
      "equal_weight",
    ]);
  });

  it("resolveObjectiveForBroad steers max_return_cvar to min_vol in broad mode", () => {
    expect(resolveObjectiveForBroad("max_return_cvar", true)).toBe("min_vol");
    expect(resolveObjectiveForBroad("max_return_cvar", false)).toBe(
      "max_return_cvar",
    );
  });
});

describe("regime_aware objective entry", () => {
  it("is exposed in ranked mode (the dropdown source)", () => {
    const values = objectivesForBroad(false).map((o) => o.value);
    expect(values).toContain("regime_aware");
  });

  it("is labelled and described in OBJECTIVES", () => {
    const entry = OBJECTIVES.find((o) => o.value === "regime_aware");
    expect(entry).toBeDefined();
    expect(entry!.label.length).toBeGreaterThan(0);
    expect(entry!.description.length).toBeGreaterThan(0);
  });

  it("broad mode EXCLUDES regime_aware (scenario-based, not covariance)", () => {
    const values = objectivesForBroad(true).map((o) => o.value);
    expect(values).not.toContain("regime_aware");
  });

  it("resolveObjectiveForBroad steers regime_aware to min_vol in broad mode", () => {
    expect(resolveObjectiveForBroad("regime_aware", true)).toBe("min_vol");
    expect(resolveObjectiveForBroad("regime_aware", false)).toBe("regime_aware");
  });
});

describe("MANDATE_CVAR_PRESETS ladder", () => {
  it("covers every Mandate key exactly", () => {
    const keys = Object.keys(MANDATE_CVAR_PRESETS).sort();
    const expected: Mandate[] = [
      "aggressive",
      "balanced",
      "conservative",
      "defensive",
      "growth",
      "moderate",
      "moderate_aggressive",
      "moderate_conservative",
    ];
    expect(keys).toEqual([...expected].sort());
  });

  it("maps mandates to daily CVaR ceilings in PERCENT, monotonically rising", () => {
    const p = MANDATE_CVAR_PRESETS;
    expect(p.conservative).toBe(1.0);
    expect(p.defensive).toBe(1.0);
    expect(p.moderate_conservative).toBe(1.5);
    expect(p.moderate).toBe(2.0);
    expect(p.balanced).toBe(2.0);
    expect(p.moderate_aggressive).toBe(2.5);
    expect(p.aggressive).toBe(3.0);
    expect(p.growth).toBe(3.5);
    for (const v of Object.values(p)) {
      expect(v).toBeGreaterThan(0);
      expect(v).toBeLessThan(10);
    }
  });
});
