// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FundUniverseCard } from "./FundUniverseCard";
import { defaultUniverseDraft, type UniverseDraft } from "./assets";

vi.mock("@/lib/api/client", () => ({
  fetchFunds: vi.fn(async () => ({ total: 100, items: [] })),
}));
vi.mock("@/components/ui/DataGrid", () => ({
  DataGrid: () => <div data-testid="datagrid" />,
}));
vi.mock("@/lib/grid/universeGridOptions", () => ({
  universePreviewToGridOptions: () => ({}),
}));

function Harness() {
  const [draft, setDraft] = useState<UniverseDraft>(defaultUniverseDraft());
  return (
    <QueryClientProvider client={new QueryClient()}>
      <FundUniverseCard
        draft={draft}
        setDraft={setDraft}
        onCount={() => {}}
        onSelectionChange={() => {}}
      />
    </QueryClientProvider>
  );
}

afterEach(cleanup);

describe("FundUniverseCard broad toggle", () => {
  it("ranked mode shows Rank by + preview; broad hides them and shows Target positions", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    // Ranked (default): rank control + preview grid present.
    expect(screen.getByLabelText("Rank funds by")).toBeInTheDocument();
    expect(screen.queryByText(/Target positions/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /broad/i }));

    // Broad: rank control gone, K slider present, preview grid gone.
    expect(screen.queryByLabelText("Rank funds by")).not.toBeInTheDocument();
    expect(screen.getByText(/Target positions/i)).toBeInTheDocument();
    expect(screen.queryByTestId("datagrid")).not.toBeInTheDocument();

    // Back to ranked restores the rank control.
    await user.click(screen.getByRole("button", { name: /ranked/i }));
    expect(screen.getByLabelText("Rank funds by")).toBeInTheDocument();
  });
});
