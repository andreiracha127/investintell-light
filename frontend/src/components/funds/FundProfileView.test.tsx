// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/charts/InteractiveChart", () => ({
  InteractiveChart: ({ range }: { range: string }) => (
    <div data-testid="interactive-chart">{range}</div>
  ),
}));

vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="highcharts-chart" />,
}));

vi.mock("@/components/funds/FundLookthroughSection", () => ({
  FundLookthroughSection: () => <div data-testid="lookthrough-section" />,
}));

vi.mock("@/lib/charts/theme", () => ({
  chartColors: () => ({
    gain: "#198038",
    loss: "#da1e28",
    accent: "#8a1538",
    accentMuted: "#b36b7d",
    accentWash: "#f7e7ec",
    textOnAccent: "#ffffff",
    text: "#161616",
    textSecondary: "#525252",
    textMuted: "#6f6f6f",
    grid: "#e0e0e0",
    surface: "#ffffff",
    bar: "#393939",
    barMute: "#8d8d8d",
    categories: [
      "#6929c4",
      "#1192e8",
      "#005d5d",
      "#9f1853",
      "#fa4d56",
      "#570408",
      "#198038",
      "#002d9c",
    ],
  }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    fetchFundProfile: vi.fn(),
    fetchFundTimeseries: vi.fn(),
  };
});

import * as client from "@/lib/api/client";
import { FundProfileView } from "@/components/funds/FundProfileView";

const mocked = vi.mocked(client);

const FUND_ID = "8a2cac81-68df-40dd-b925-0e6350d6a0de";

function makeProfile(): client.FundProfile {
  return {
    instrument_id: FUND_ID,
    series_id: "VFINX-series",
    ticker: "VFINX",
    isin: null,
    cusip: null,
    lei: null,
    name: "Vanguard 500 Index Fund",
    fund_type: "mutual_fund",
    strategy_label: "Large blend",
    asset_class: "equity",
    is_index: true,
    expense_ratio: 0.0001,
    aum_usd: 1_500_000_000_000,
    primary_benchmark: "SPY",
    inception_date: "1976-08-31",
    domicile: "US",
    currency: "USD",
    synced_at: "2026-06-12T00:00:00Z",
    source_calc_date: "2026-06-12",
    source_nav_max_date: "2026-06-12",
    risk: null,
    nav: [],
    holdings: {
      report_date: null,
      items: [],
      pct_of_nav_total: null,
    },
    classes: [],
    classification_note: "Classification note",
  };
}

function renderFundProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FundProfileView instrumentId={FUND_ID} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FundProfileView", () => {
  it("loads the interactive NAV chart by range and analytics charts from MAX timeseries", async () => {
    mocked.fetchFundProfile.mockResolvedValue(makeProfile());
    mocked.fetchFundTimeseries.mockImplementation(async (instrumentId, range) => ({
      id: instrumentId,
      interval: range === "MAX" ? "monthly" : "daily",
      series: [
        [Date.UTC(2025, 5, 12), 100],
        [Date.UTC(2026, 5, 12), 125],
      ],
    }));

    renderFundProfile();

    await waitFor(() =>
      expect(mocked.fetchFundTimeseries).toHaveBeenCalledTimes(2),
    );
    expect(mocked.fetchFundTimeseries.mock.calls.map((call) => call[1])).toEqual(
      expect.arrayContaining(["1Y", "MAX"]),
    );
  });
});
