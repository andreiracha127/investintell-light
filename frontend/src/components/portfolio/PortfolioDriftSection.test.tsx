// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PortfolioAlerts } from "@/lib/api/client";

const getMock = vi.fn<(...args: never[]) => Promise<PortfolioAlerts>>();

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>(
    "@/lib/api/client",
  );
  return {
    ...actual,
    getPortfolioAlerts: () => getMock(),
  };
});

import { PortfolioDriftSection } from "./PortfolioDriftSection";

function renderSection() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PortfolioDriftSection portfolioId={7} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  getMock.mockReset();
});

const emptyAlerts: PortfolioAlerts = {
  evaluated_at: null,
  worst_status: "ok",
  breaches: {
    position_drifts: [],
    class_breaches: [],
    overlap_breaches: [],
    overlap_report_date: null,
  },
};

describe("PortfolioDriftSection", () => {
  it("renders the worst_status badge and one of each breach type", async () => {
    getMock.mockResolvedValue({
      evaluated_at: "2026-06-20T12:00:00Z",
      worst_status: "urgent",
      breaches: {
        position_drifts: [
          {
            ticker: "AAPL",
            current_weight: 0.4,
            target_weight: 0.2,
            drift_abs: 0.2,
            drift_rel: 1.0,
            breach: true,
            status: "urgent",
          },
        ],
        class_breaches: [
          {
            asset_class: "equity",
            current_weight: 0.9,
            min_weight: null,
            max_weight: 0.7,
            kind: "above_max",
          },
        ],
        overlap_breaches: [
          { security_key: "MSFT", exposure: 0.7, overlap_cap: 0.6 },
        ],
        overlap_report_date: "2026-05-31",
      },
    });

    renderSection();

    // Status badge reflects worst_status.
    const badge = await screen.findByLabelText(/drift status: urgent/i);
    expect(badge).toBeTruthy();

    // Each breach renders with its identifying value.
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText(/equity/i)).toBeTruthy();
    expect(screen.getByText("MSFT")).toBeTruthy();
  });

  it("shows the no-alerts message when the set is empty", async () => {
    getMock.mockResolvedValue(emptyAlerts);

    renderSection();

    expect(await screen.findByLabelText(/drift status: ok/i)).toBeTruthy();
    expect(screen.getByText(/no drift alerts/i)).toBeTruthy();
  });
});
