// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  OptimizeJobAccepted,
  OptimizeJobStatus,
  OptimizeRequest,
} from "@/lib/api/client";

/* ── Spies ──────────────────────────────────────────────────────────────── */

const resultsPanelMock = vi.hoisted(() =>
  vi.fn((props: unknown) => {
    void props;
    return <div data-testid="results" />;
  }),
);

// Sync path: must NEVER be called in broad mode.
const optimizeMock = vi.fn(async (body: OptimizeRequest) => {
  void body;
  throw new Error("sync optimize should not run in broad mode");
});

const optimizeAsyncMock = vi.fn(
  async (body: OptimizeRequest): Promise<OptimizeJobAccepted> => {
    void body;
    return { job_id: "job-123" };
  },
);

// Poll sequence: pending → running → succeeded (then unused tail).
const succeededResult = {
  weights: [{ asset: { kind: "equity", ticker: "AAPL" }, weight: 1 }],
  expected: { vol_ann: 0.1, cvar_95_in_sample: 0.02, return_ann_bl: null },
  diagnostics: {
    n_obs: 500,
    status: "optimal",
    mu_equilibrium: null,
    mu_posterior: null,
    view_consistency: null,
    selection: null,
    cvar_limit_effective: 0.01,
    regime_state: null,
  },
};

const jobSequence: OptimizeJobStatus[] = [
  { status: "pending", result: null, error: null },
  { status: "running", result: null, error: null },
  // @ts-expect-error — test fixture is a structurally-valid OptimizeResponse
  { status: "succeeded", result: succeededResult, error: null },
];
let jobCallIndex = 0;
const getJobMock = vi.fn(async (jobId: string): Promise<OptimizeJobStatus> => {
  void jobId;
  const i = Math.min(jobCallIndex, jobSequence.length - 1);
  jobCallIndex += 1;
  return jobSequence[i];
});

vi.mock("@/lib/api/client", () => ({
  postBuilderOptimize: (body: OptimizeRequest) => optimizeMock(body),
  postBuilderOptimizeAsync: (body: OptimizeRequest) => optimizeAsyncMock(body),
  getBuilderOptimizeJob: (jobId: string) => getJobMock(jobId),
  fetchPortfolioOverview: vi.fn(),
}));
vi.mock("@/lib/charts/chartColors", () => ({
  chartColors: () => null,
}));

// Broad-universe card: a button that flips the draft into broad mode and
// reports a count ≥ 2 so the run is enabled.
vi.mock("./FundUniverseCard", () => ({
  FundUniverseCard: ({
    setDraft,
    onCount,
  }: {
    setDraft: (u: (p: Record<string, unknown>) => Record<string, unknown>) => void;
    onCount: (count: number | null) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        setDraft((prev) => ({ ...prev, broadUniverse: true }));
        onCount(42);
      }}
    >
      enable-broad
    </button>
  ),
}));
vi.mock("./UniverseCard", () => ({ UniverseCard: () => <div /> }));
vi.mock("./ViewsCard", () => ({
  ViewsCard: () => <div />,
  toApiView: () => null,
}));
vi.mock("./ResultsPanel", () => ({
  ResultsPanel: (props: unknown) => resultsPanelMock(props),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

import { BuilderView } from "./BuilderView";

function renderView() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <BuilderView />
    </QueryClientProvider>,
  );
}

async function startBroadRun() {
  const user = userEvent.setup();
  renderView();
  // Switch to the fund-universe mode, then enable broad + count.
  await user.click(screen.getByRole("tab", { name: /search the fund universe/i }));
  await user.click(screen.getByRole("button", { name: "enable-broad" }));
  await user.click(screen.getByRole("button", { name: /suggest weights/i }));
  return user;
}

afterEach(() => {
  cleanup();
  optimizeMock.mockClear();
  optimizeAsyncMock.mockClear();
  getJobMock.mockClear();
  resultsPanelMock.mockClear();
  jobCallIndex = 0;
});

describe("BuilderView broad-universe async job", () => {
  it("dispatches the async job and polls pending→running→succeeded into ResultsPanel", async () => {
    await startBroadRun();

    // Dispatched via the async endpoint, never the synchronous one.
    await waitFor(() => expect(optimizeAsyncMock).toHaveBeenCalledTimes(1));
    expect(optimizeMock).not.toHaveBeenCalled();
    const body = optimizeAsyncMock.mock.calls[0]?.[0];
    expect(body?.universe?.broad_universe).toBe(true);

    // Polls until the job is terminal and feeds `result` to ResultsPanel.
    await waitFor(
      () => {
        const props = resultsPanelMock.mock.calls.at(-1)?.[0] as
          | { result: { weights: unknown[] } }
          | undefined;
        expect(props?.result?.weights).toHaveLength(1);
      },
      { timeout: 5000 },
    );
    expect(getJobMock).toHaveBeenCalled();
  });

  it("surfaces the error message when the job fails", async () => {
    jobSequence.splice(
      0,
      jobSequence.length,
      { status: "pending", result: null, error: null },
      { status: "failed", result: null, error: "no funds matched the filters" },
    );

    await startBroadRun();

    await waitFor(
      () =>
        expect(
          screen.getByText(/no funds matched the filters/i),
        ).toBeInTheDocument(),
      { timeout: 5000 },
    );
    expect(resultsPanelMock).not.toHaveBeenCalled();

    // Restore the success sequence for any later test ordering.
    jobSequence.splice(
      0,
      jobSequence.length,
      { status: "pending", result: null, error: null },
      { status: "running", result: null, error: null },
      // @ts-expect-error — test fixture is a structurally-valid OptimizeResponse
      { status: "succeeded", result: succeededResult, error: null },
    );
  });
});
