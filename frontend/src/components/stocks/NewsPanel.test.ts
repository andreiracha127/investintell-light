import { describe, expect, it } from "vitest";

import { formatNewsRecency } from "@/components/stocks/NewsPanel";

describe("formatNewsRecency", () => {
  const now = Date.parse("2026-07-02T12:00:00Z");

  it("shows minutes for sub-hour timestamps", () => {
    const publishedAt = "2026-07-02T11:25:00Z";
    expect(formatNewsRecency(publishedAt, now)).toBe("35m ago");
  });

  it("shows hours for same-day but older-than-an-hour timestamps", () => {
    const publishedAt = "2026-07-02T09:30:00Z";
    expect(formatNewsRecency(publishedAt, now)).toBe("2h ago");
  });

  it("falls back to a formatted date at 24h and beyond", () => {
    const publishedAt = "2026-06-29T12:00:00Z";
    expect(formatNewsRecency(publishedAt, now)).toBe("Jun 29, 2026");
  });

  it("treats a fresh timestamp as just now", () => {
    const publishedAt = "2026-07-02T11:59:40Z";
    expect(formatNewsRecency(publishedAt, now)).toBe("just now");
  });

  it("falls back to a formatted date for unparseable input", () => {
    expect(formatNewsRecency("not-a-date", now)).toBe("—");
  });
});
