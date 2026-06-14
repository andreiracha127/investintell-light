import { describe, expect, it } from "vitest";

import { flashClassForDir } from "./liveFlash";

describe("flashClassForDir", () => {
  it("maps +1 (price up) to the gain flash class", () => {
    expect(flashClassForDir(1)).toBe("ix-grid-flash-up");
  });

  it("maps -1 (price down) to the loss flash class", () => {
    expect(flashClassForDir(-1)).toBe("ix-grid-flash-down");
  });

  it("maps 0 (unchanged) to null — no flash", () => {
    expect(flashClassForDir(0)).toBeNull();
  });
});
