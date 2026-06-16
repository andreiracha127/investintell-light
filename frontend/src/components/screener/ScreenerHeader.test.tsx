// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen as dom,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Screen, ScreenListItem } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  createScreen: vi.fn(),
  patchScreen: vi.fn(),
  deleteScreen: vi.fn(),
}));

import * as client from "@/lib/api/client";
import { ScreenerHeader } from "@/components/screener/ScreenerHeader";

const mocked = vi.mocked(client);

const SCREENS: ScreenListItem[] = [
  {
    id: 1,
    name: "Tech growth",
    filter_count: 3,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
  },
  {
    id: 2,
    name: "Value picks",
    filter_count: 1,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
  },
];

function makeScreen(id: number, name: string): Screen {
  return {
    id,
    name,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
    filters: [],
  };
}

type SaveStatus = "idle" | "saving" | "error";

function renderHeader(
  props: Partial<{
    screens: ScreenListItem[];
    selected: ScreenListItem | null;
    onSelect: (id: number | null) => void;
    headline: number | null;
    saveStatus: SaveStatus;
    onReset: () => void;
    onExport: () => void;
    exporting: boolean;
  }> = {},
) {
  const onSelect = props.onSelect ?? vi.fn();
  const onReset = props.onReset ?? vi.fn();
  const onExport = props.onExport ?? vi.fn();
  // Respect explicit `null` (don't let ?? fall back) for nullable props.
  const selected = "selected" in props ? (props.selected ?? null) : SCREENS[0];
  const headline = "headline" in props ? (props.headline ?? null) : 42;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ScreenerHeader
        screens={props.screens ?? SCREENS}
        selected={selected}
        onSelect={onSelect}
        headline={headline}
        saveStatus={props.saveStatus ?? "idle"}
        onReset={onReset}
        onExport={onExport}
        exporting={props.exporting ?? false}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onSelect, onReset, onExport };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScreenerHeader", () => {
  it("1. save indicator: renders text per saveStatus", () => {
    const { rerender } = renderHeader({ saveStatus: "idle" });
    expect(dom.getByText("Saved ✓")).toBeInTheDocument();

    const qc = new QueryClient();
    rerender(
      <QueryClientProvider client={qc}>
        <ScreenerHeader
          screens={SCREENS}
          selected={SCREENS[0]}
          onSelect={vi.fn()}
          headline={42}
          saveStatus="saving"
          onReset={vi.fn()}
          onExport={vi.fn()}
          exporting={false}
        />
      </QueryClientProvider>,
    );
    expect(dom.getByText("Saving…")).toBeInTheDocument();

    rerender(
      <QueryClientProvider client={qc}>
        <ScreenerHeader
          screens={SCREENS}
          selected={SCREENS[0]}
          onSelect={vi.fn()}
          headline={42}
          saveStatus="error"
          onReset={vi.fn()}
          onExport={vi.fn()}
          exporting={false}
        />
      </QueryClientProvider>,
    );
    expect(dom.getByText("Save failed — retry")).toBeInTheDocument();
  });

  it("2. match count: renders formatted headline, and '— matches' when null", () => {
    const { unmount } = renderHeader({ headline: 42 });
    expect(dom.getByText("42 matches")).toBeInTheDocument();
    unmount();

    renderHeader({ headline: null });
    expect(dom.getByText("— matches")).toBeInTheDocument();
  });

  it("3. switch: opening the menu and clicking another screen calls onSelect", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderHeader();

    await user.click(dom.getByRole("button", { name: /Tech growth/ }));
    await user.click(dom.getByRole("menuitem", { name: /Value picks/ }));

    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("4. new: prompt → createScreen(name); on resolve onSelect(created id)", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "prompt").mockReturnValue("New X");
    mocked.createScreen.mockResolvedValue(makeScreen(7, "New X"));
    const { onSelect } = renderHeader();

    await user.click(dom.getByRole("button", { name: /Tech growth/ }));
    await user.click(dom.getByRole("button", { name: "+ New screen" }));

    expect(mocked.createScreen).toHaveBeenCalledWith({ name: "New X" });
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(7));
  });

  it("5. rename: menu → Rename → type + Enter → patchScreen(id, {name})", async () => {
    const user = userEvent.setup();
    mocked.patchScreen.mockResolvedValue(makeScreen(1, "Renamed"));
    renderHeader();

    await user.click(dom.getByRole("button", { name: /Tech growth/ }));
    await user.click(dom.getByRole("button", { name: "Rename" }));

    const input = dom.getByRole("textbox", { name: "Rename screen" });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");

    await waitFor(() =>
      expect(mocked.patchScreen).toHaveBeenCalledWith(1, { name: "Renamed" }),
    );
  });

  it("6. delete: confirm → deleteScreen(id); on resolve onSelect(null)", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocked.deleteScreen.mockResolvedValue(undefined);
    const { onSelect } = renderHeader();

    await user.click(dom.getByRole("button", { name: /Tech growth/ }));
    await user.click(dom.getByRole("button", { name: "Delete" }));

    expect(mocked.deleteScreen).toHaveBeenCalledWith(1);
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
  });

  it("7a. reset: calls onReset; disabled when nothing selected", async () => {
    const user = userEvent.setup();
    const { onReset, unmount } = renderHeader({ selected: SCREENS[0] });
    await user.click(dom.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledTimes(1);
    unmount();

    renderHeader({ selected: null });
    expect(dom.getByRole("button", { name: "Reset" })).toBeDisabled();
  });

  it("7b. export: calls onExport; shows 'Exporting…' when exporting", async () => {
    const user = userEvent.setup();
    const { onExport, unmount } = renderHeader({ exporting: false });
    await user.click(dom.getByRole("button", { name: /Export CSV/ }));
    expect(onExport).toHaveBeenCalledTimes(1);
    unmount();

    renderHeader({ exporting: true });
    expect(dom.getByText("Exporting…")).toBeInTheDocument();
  });

  it("8a. menu dismissal: Escape closes the open menu", async () => {
    const user = userEvent.setup();
    renderHeader();

    const trigger = dom.getByRole("button", { name: /Tech growth/ });
    await user.click(trigger);
    expect(dom.getByRole("menu")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(dom.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("8b. menu dismissal: mousedown outside closes the open menu", async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(dom.getByRole("button", { name: /Tech growth/ }));
    expect(dom.getByRole("menu")).toBeInTheDocument();

    // A mousedown anywhere outside the switcher container closes it.
    await user.click(document.body);
    await waitFor(() =>
      expect(dom.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });
});
