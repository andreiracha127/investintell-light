// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen as dom, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BuildAll,
  FilterUpdateResponse,
  MetricDef,
  Screen,
} from "@/lib/api/client";
import type { FiltersGridCallbacks } from "@/lib/grid/filtersGridOptions";

// ── API client: mock the network functions, keep the real shared helpers ──
vi.mock("@/lib/api/client", () => ({
  fetchScreenBuildAll: vi.fn(),
  putScreenFilter: vi.fn(),
  deleteScreenFilter: vi.fn(),
  reorderScreenFilters: vi.fn(),
  createScreen: vi.fn(),
}));

// ── Leaf doubles: surface BuildPanel's callbacks as clickable buttons ──
// AddMetricBar → one "add" button per relevant code (a not-present and a present one).
vi.mock("@/components/screener/AddMetricBar", () => ({
  AddMetricBar: ({
    onToggleMetric,
  }: {
    onToggleMetric: (code: string) => void;
  }) => (
    <div data-testid="add-metric-bar">
      <button type="button" onClick={() => onToggleMetric("roe")}>
        add roe
      </button>
      <button type="button" onClick={() => onToggleMetric("pe_ratio")}>
        toggle pe_ratio
      </button>
    </div>
  ),
}));

// FiltersGrid → buttons invoking each grid callback with fixed args.
vi.mock("@/components/screener/FiltersGrid", () => ({
  FiltersGrid: ({ callbacks }: { callbacks: FiltersGridCallbacks }) => (
    <div data-testid="filters-grid">
      <button
        type="button"
        onClick={() => callbacks.onEditBound("pe_ratio", "max", 30)}
      >
        grid edit pe max 30
      </button>
      <button type="button" onClick={() => callbacks.onRemove("pe_ratio")}>
        grid remove pe
      </button>
      <button type="button" onClick={() => callbacks.onMove("pe_ratio", "down")}>
        grid move pe down
      </button>
      <button
        type="button"
        onClick={() => callbacks.onToggleSelect("pe_ratio", true)}
      >
        grid select pe
      </button>
      <button type="button" onClick={() => callbacks.onSelectRow("market_cap")}>
        grid activate market_cap
      </button>
    </div>
  ),
}));

// DistributionPanel → echoes the active metric code so we can assert active-row.
vi.mock("@/components/screener/DistributionPanel", () => ({
  DistributionPanel: ({ metric }: { metric: MetricDef }) => (
    <div data-testid="dist-panel">{metric.code}</div>
  ),
}));

import * as client from "@/lib/api/client";
import { BuildPanel } from "@/components/screener/BuildPanel";

// ── Fixtures ──────────────────────────────────────────────────────────────
const PE: MetricDef = {
  code: "pe_ratio",
  name: "Price / Earnings (TTM)",
  abbreviation: "P/E",
  category: "Fundamentals: Valuation",
  sub_category: "Multiples",
  data_type: "float",
  scale_note: "",
  presets: [],
};
const MKT_CAP: MetricDef = {
  ...PE,
  code: "market_cap",
  name: "Market Cap",
  abbreviation: "Mkt Cap",
  data_type: "currency",
};
const ROE: MetricDef = {
  ...PE,
  code: "roe",
  name: "Return on Equity",
  abbreviation: "ROE",
  data_type: "percent",
};
const CATALOG: MetricDef[] = [PE, MKT_CAP, ROE];

function makeScreen(overrides: Partial<Screen> = {}): Screen {
  return {
    id: 1,
    name: "My screen",
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
    filters: [
      { metric_code: "pe_ratio", min_value: null, max_value: 25, position: 0 },
      {
        metric_code: "market_cap",
        min_value: 1_000_000,
        max_value: null,
        position: 1,
      },
    ],
    ...overrides,
  };
}

const BUILD_ALL: BuildAll = {
  headline_count: 42,
  metrics: [
    { metric_code: "pe_ratio", available_count: 100, distribution: null },
    { metric_code: "market_cap", available_count: 100, distribution: null },
  ],
};

/** Realistic FilterUpdateResponse so applyFilterResponse + onHeadline work. */
function filterResp(screen: Screen): FilterUpdateResponse {
  return { screen, distribution: null, headline_count: 7, available_count: 0 };
}

const mocked = vi.mocked(client);

function renderBuildPanel(props: {
  screen: Screen | null;
  onScreenCreated?: (id: number) => void;
  onHeadline?: (count: number | null) => void;
  onSaveStatus?: (status: "idle" | "saving" | "error") => void;
}) {
  const onScreenCreated = props.onScreenCreated ?? vi.fn();
  const onHeadline = props.onHeadline ?? vi.fn();
  const onSaveStatus = props.onSaveStatus ?? vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <BuildPanel
        screen={props.screen}
        catalog={CATALOG}
        onScreenCreated={onScreenCreated}
        onHeadline={onHeadline}
        onSaveStatus={onSaveStatus}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onScreenCreated, onHeadline, onSaveStatus };
}

beforeEach(() => {
  mocked.fetchScreenBuildAll.mockResolvedValue(BUILD_ALL);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BuildPanel", () => {
  it("1. add: clicking add for a not-present code PUTs an unbounded filter", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });
    mocked.putScreenFilter.mockResolvedValue(filterResp(makeScreen()));

    await user.click(dom.getByRole("button", { name: "add roe" }));

    await waitFor(() =>
      expect(mocked.putScreenFilter).toHaveBeenCalledWith(1, "roe", {
        min_value: null,
        max_value: null,
      }),
    );
  });

  it("2. add with lazy screen creation: creates then PUTs, fires onScreenCreated", async () => {
    const user = userEvent.setup();
    const created: Screen = makeScreen({ id: 99, filters: [] });
    mocked.createScreen.mockResolvedValue(created);
    mocked.putScreenFilter.mockResolvedValue(filterResp(created));
    const { onScreenCreated } = renderBuildPanel({ screen: null });

    await user.click(dom.getByRole("button", { name: "add roe" }));

    await waitFor(() =>
      expect(mocked.createScreen).toHaveBeenCalledWith({
        name: "Untitled screen",
      }),
    );
    await waitFor(() =>
      expect(mocked.putScreenFilter).toHaveBeenCalledWith(99, "roe", {
        min_value: null,
        max_value: null,
      }),
    );
    expect(onScreenCreated).toHaveBeenCalledWith(99);
  });

  it("3. edit-bound: PUTs the edited bound, preserving the other", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });
    mocked.putScreenFilter.mockResolvedValue(filterResp(makeScreen()));

    await user.click(
      await dom.findByRole("button", { name: "grid edit pe max 30" }),
    );

    // pe_ratio had min_value:null, max_value:25 → editing max keeps min null.
    await waitFor(() =>
      expect(mocked.putScreenFilter).toHaveBeenCalledWith(1, "pe_ratio", {
        min_value: null,
        max_value: 30,
      }),
    );
  });

  it("4. remove: DELETEs the filter", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });
    mocked.deleteScreenFilter.mockResolvedValue(filterResp(makeScreen()));

    await user.click(
      await dom.findByRole("button", { name: "grid remove pe" }),
    );

    await waitFor(() =>
      expect(mocked.deleteScreenFilter).toHaveBeenCalledWith(1, "pe_ratio"),
    );
  });

  it("5. mass-delete: selecting shows the bar; clicking it DELETEs each + clears", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });
    mocked.deleteScreenFilter.mockResolvedValue(filterResp(makeScreen()));

    await user.click(
      await dom.findByRole("button", { name: "grid select pe" }),
    );

    const deleteSelected = await dom.findByRole("button", {
      name: /Delete 1 selected/,
    });
    await user.click(deleteSelected);

    await waitFor(() =>
      expect(mocked.deleteScreenFilter).toHaveBeenCalledWith(1, "pe_ratio"),
    );
    // Selection cleared → the mass-delete bar disappears.
    await waitFor(() =>
      expect(
        dom.queryByRole("button", { name: /Delete 1 selected/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it("6. reorder/move: down swaps order and reorders with swapped codes", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });
    mocked.reorderScreenFilters.mockResolvedValue(makeScreen());

    await user.click(
      await dom.findByRole("button", { name: "grid move pe down" }),
    );

    await waitFor(() =>
      expect(mocked.reorderScreenFilters).toHaveBeenCalledWith(1, [
        "market_cap",
        "pe_ratio",
      ]),
    );
  });

  it("7a. active-row: selecting a row shows it in the DistributionPanel", async () => {
    const user = userEvent.setup();
    renderBuildPanel({ screen: makeScreen() });

    // Default active row = first filter (pe_ratio).
    expect(await dom.findByTestId("dist-panel")).toHaveTextContent("pe_ratio");

    await user.click(
      dom.getByRole("button", { name: "grid activate market_cap" }),
    );
    await waitFor(() =>
      expect(dom.getByTestId("dist-panel")).toHaveTextContent("market_cap"),
    );
  });

  it("7b. empty state shows when the screen has no filters", () => {
    renderBuildPanel({ screen: makeScreen({ filters: [] }) });
    expect(dom.getByText(/No metrics yet/)).toBeInTheDocument();
    expect(dom.queryByTestId("filters-grid")).not.toBeInTheDocument();
  });

  it("8. headline + saveStatus: onHeadline(42) after build; saving→idle around a PUT", async () => {
    const user = userEvent.setup();
    const onHeadline = vi.fn();
    const onSaveStatus = vi.fn();
    renderBuildPanel({ screen: makeScreen(), onHeadline, onSaveStatus });
    mocked.putScreenFilter.mockResolvedValue(filterResp(makeScreen()));

    // Build query resolves → headline reported.
    await waitFor(() => expect(onHeadline).toHaveBeenCalledWith(42));

    await user.click(dom.getByRole("button", { name: "add roe" }));

    await waitFor(() =>
      expect(onSaveStatus).toHaveBeenCalledWith("saving"),
    );
    await waitFor(() => expect(onSaveStatus).toHaveBeenCalledWith("idle"));
    // The mutation response's headline_count (7) is also reported.
    await waitFor(() => expect(onHeadline).toHaveBeenCalledWith(7));
  });
});
