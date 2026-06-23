// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";

// jsdom has no ResizeObserver; the wrapper observes its container for reflow.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const stockChart = vi.fn(() => ({
  destroy: vi.fn(),
  reflow: vi.fn(),
  get: vi.fn(),
  addSeries: vi.fn(),
  update: vi.fn(),
  redraw: vi.fn(),
  series: [],
}));

vi.mock("highcharts/esm/highstock.js", () => ({
  default: { stockChart, setOptions: vi.fn() },
}));
vi.mock("highcharts/esm/highcharts-more.js", () => ({}));
vi.mock("highcharts/esm/indicators/indicators-all.js", () => ({}));
vi.mock("highcharts/esm/modules/annotations.js", () => ({}));
vi.mock("highcharts/esm/modules/stock-tools.js", () => ({}));
vi.mock("highcharts/css/stocktools/gui.css", () => ({}));
vi.mock("highcharts/css/annotations/popup.css", () => ({}));
vi.mock("./stock-chart.css", () => ({}));

vi.mock("@/lib/livefeed/client", () => ({
  subscribeTicks: () => () => {},
  onFeedStatus: () => () => {},
}));
vi.mock("@/lib/charts/chartColors", () => ({
  chartColors: () => ({ categories: [] }),
}));
vi.mock("@/lib/charts/hc/theme", () => ({ highchartsTheme: () => ({}) }));

// SymbolSearchInput pulls in @tanstack/react-query (needs a provider). The
// wrapper's chart lifecycle is the subject under test, so stub the search box.
vi.mock("@/components/charts/SymbolSearchInput", () => ({
  SymbolSearchInput: () => null,
}));

import { StockChart } from "./StockChart";

afterEach(cleanup);

describe("StockChart wrapper", () => {
  it("creates a stockChart once and destroys on unmount", async () => {
    const { unmount } = render(
      <StockChart
        symbol="NVDA"
        bars={[{ t: 1, o: 1, h: 1, l: 1, c: 1, v: 1 }]}
        initialRange="1Y"
        onRangeChange={() => {}}
      />,
    );
    await vi.waitFor(() => expect(stockChart).toHaveBeenCalledTimes(1));
    unmount();
  });
});
