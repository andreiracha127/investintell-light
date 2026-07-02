import { describe, expect, it } from "vitest";

import type { FiscalSeries } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import {
  buildHcMacroFiscalOption,
  fiscalSeriesLabel,
} from "@/lib/charts/hc/macro-fiscal";
import { formatCompact, formatDate, formatNumber } from "@/lib/format";

const SERIES: FiscalSeries[] = [
  {
    series_id: "RATE_10Y_TREASURY",
    points: [
      { obs_date: "2024-01-02", value: 4.02, metadata: null },
      { obs_date: "2024-01-03", value: 3.98, metadata: null },
    ],
  },
  {
    series_id: "RATE_2Y_TREASURY",
    points: [{ obs_date: "2024-01-02", value: 4.35, metadata: null }],
  },
];

function build(overrides: Partial<Parameters<typeof buildHcMacroFiscalOption>[0]> = {}) {
  return buildHcMacroFiscalOption({
    series: SERIES,
    category: "rates",
    prefix: "RATE_",
    colors: TEST_COLORS,
    ...overrides,
  });
}

describe("fiscalSeriesLabel", () => {
  it("strips the worker prefix and title-cases words", () => {
    expect(fiscalSeriesLabel("DEBT_TOTAL_PUBLIC_DEBT", "DEBT_")).toBe(
      "Total Public Debt",
    );
  });

  it("keeps tenor-style tokens uppercase (digits / short words)", () => {
    expect(fiscalSeriesLabel("RATE_10Y_TREASURY", "RATE_")).toBe("10Y Treasury");
  });

  it("leaves ids without the prefix untouched apart from casing", () => {
    expect(fiscalSeriesLabel("NFCI_INDEX", "RATE_")).toBe("Nfci Index");
  });
});

describe("buildHcMacroFiscalOption", () => {
  // ── Data mapping ─────────────────────────────────────────────────────────

  it("maps every fiscal series to a named line series", () => {
    const opt = build();
    const series = opt.series as Array<{ type?: string; name?: string }>;
    expect(series).toHaveLength(2);
    expect(series[0].type).toBe("line");
    expect(series[0].name).toBe("10Y Treasury");
    expect(series[1].name).toBe("2Y Treasury");
  });

  it("maps obs_date/value points to UTC datetime pairs", () => {
    const opt = build();
    const series = opt.series?.[0] as { data?: Array<[number, number]> };
    expect(series.data).toEqual([
      [dateToUtcMs("2024-01-02"), 4.02],
      [dateToUtcMs("2024-01-03"), 3.98],
    ]);
  });

  it("assigns category palette colors per series", () => {
    const opt = build();
    const series = opt.series as Array<{ color?: string }>;
    expect(series[0].color).toBe(TEST_COLORS.categories[0]);
    expect(series[1].color).toBe(TEST_COLORS.categories[1]);
  });

  // ── Stock chrome ──────────────────────────────────────────────────────────

  it("enables navigator + scrollbar and disables the rangeSelector", () => {
    const opt = build();
    expect((opt.navigator as { enabled?: boolean }).enabled).toBe(true);
    expect((opt.scrollbar as { enabled?: boolean }).enabled).toBe(true);
    expect((opt.rangeSelector as { enabled?: boolean }).enabled).toBe(false);
  });

  it("uses a non-ordinal datetime x-axis (calendar-spaced observations)", () => {
    const opt = build();
    const xAxis = opt.xAxis as { type?: string; ordinal?: boolean };
    expect(xAxis.type).toBe("datetime");
    expect(xAxis.ordinal).toBe(false);
  });

  it("enables the legend for multi-series reading", () => {
    const opt = build();
    expect((opt.legend as { enabled?: boolean }).enabled).toBe(true);
  });

  // ── Value formatting by category ──────────────────────────────────────────

  it("formats rates category y labels as percent", () => {
    const opt = build({ category: "rates" });
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(yAxis.labels!.formatter!.call({ value: 4.25 })).toBe(
      `${formatNumber(4.25)}%`,
    );
  });

  it("formats debt category y labels compactly (dollar levels)", () => {
    const opt = build({ category: "debt", prefix: "DEBT_" });
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(yAxis.labels!.formatter!.call({ value: 34_500_000_000_000 })).toBe(
      formatCompact(34_500_000_000_000),
    );
  });

  it("renders a shared tooltip with one row per point", () => {
    const opt = build();
    const tooltip = opt.tooltip as {
      shared?: boolean;
      formatter?: (this: {
        x: number;
        points?: Array<{ color?: string; y?: number; series: { name: string } }>;
      }) => string;
    };
    expect(tooltip.shared).toBe(true);
    const out = tooltip.formatter!.call({
      x: dateToUtcMs("2024-01-02"),
      points: [
        { color: "#111", y: 4.02, series: { name: "10Y Treasury" } },
        { color: "#222", y: 4.35, series: { name: "2Y Treasury" } },
      ],
    });
    expect(out).toContain(formatDate("2024-01-02"));
    expect(out).toContain("10Y Treasury");
    expect(out).toContain(`${formatNumber(4.35)}%`);
  });

  // ── Empty input ───────────────────────────────────────────────────────────

  it("returns no series for empty input", () => {
    const opt = build({ series: [] });
    expect(opt.series).toEqual([]);
  });

  // ── Chart-level structure ─────────────────────────────────────────────────

  it("does not re-set global chrome (theme owns grid/tooltip styling)", () => {
    const opt = build();
    const yAxis = opt.yAxis as Record<string, unknown>;
    expect(yAxis.gridLineColor).toBeUndefined();
    const tooltip = opt.tooltip as Record<string, unknown>;
    expect(tooltip.backgroundColor).toBeUndefined();
  });
});
