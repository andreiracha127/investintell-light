// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  PortfolioConstraints,
  PortfolioConstraintsPut,
} from "@/lib/api/client";

const getMock =
  vi.fn<(...args: never[]) => Promise<PortfolioConstraints>>();
const putMock =
  vi.fn<
    (id: number, body: PortfolioConstraintsPut) => Promise<PortfolioConstraints>
  >();

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>(
    "@/lib/api/client",
  );
  return {
    ...actual,
    getPortfolioConstraints: () => getMock(),
    putPortfolioConstraints: (id: number, body: PortfolioConstraintsPut) =>
      putMock(id, body),
  };
});

import { PortfolioConstraintsSection } from "./PortfolioConstraintsSection";

function renderSection() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PortfolioConstraintsSection portfolioId={7} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  getMock.mockReset();
  putMock.mockReset();
});

const emptyConstraints: PortfolioConstraints = {
  portfolio_id: 7,
  cap: null,
  min_weight: null,
  overlap_cap: null,
  class_limits: [],
};

describe("PortfolioConstraintsSection", () => {
  it("loads the persisted constraints via GET and pre-fills the fields", async () => {
    getMock.mockResolvedValue({
      portfolio_id: 7,
      cap: 0.3,
      min_weight: 0.01,
      overlap_cap: 0.2,
      class_limits: [{ asset_class: "equity", min_weight: 0.1, max_weight: 0.6 }],
    });

    renderSection();

    await waitFor(() =>
      expect(
        (screen.getByLabelText("Max per holding") as HTMLInputElement).value,
      ).toBe("30"),
    );
    expect((screen.getByLabelText("Min per holding") as HTMLInputElement).value).toBe(
      "1",
    );
    expect((screen.getByLabelText("Overlap cap") as HTMLInputElement).value).toBe(
      "20",
    );
  });

  it("edits a field and PUTs the updated set (percent → fraction)", async () => {
    getMock.mockResolvedValue(emptyConstraints);
    putMock.mockResolvedValue(emptyConstraints);

    const user = userEvent.setup();
    renderSection();

    const cap = await screen.findByLabelText("Max per holding");
    await user.clear(cap);
    await user.type(cap, "40");

    const overlap = screen.getByLabelText("Overlap cap");
    await user.type(overlap, "15");

    await user.click(screen.getByRole("button", { name: /save constraints/i }));

    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const [id, body] = putMock.mock.calls[0]!;
    expect(id).toBe(7);
    expect(body.cap).toBeCloseTo(0.4, 6);
    expect(body.overlap_cap).toBeCloseTo(0.15, 6);
    expect(body.min_weight).toBeNull();
    expect(body.class_limits).toEqual([]);
  });
});
