import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  postBacktestWalkForward,
  postPortfolioMonteCarlo,
  type PortfolioMonteCarloRequest,
  type WalkForwardRequest,
} from "@/lib/api/client";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    statusText: "OK",
    headers: { "Content-Type": "application/json" },
  });
}

function errJson(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    statusText: "Unprocessable Entity",
    headers: { "Content-Type": "application/json" },
  });
}

const WF_REQ: WalkForwardRequest = {
  assets: [{ kind: "equity", ticker: "SPY" }],
  objective: "min_cvar",
  constraints: { cap: 0.25 },
  n_splits: 5,
  gap: 2,
  test_size: 63,
  min_train_size: 252,
  cost_bps: 10,
  risk_free_annual: 0,
};

const MC_REQ: PortfolioMonteCarloRequest = {
  positions: [{ asset: { kind: "equity", ticker: "SPY" }, weight: 1 }],
  statistic: "return",
  n_simulations: 10000,
  risk_free_rate: 0.04,
};

describe("postBacktestWalkForward", () => {
  it("POSTs /backtest/walk-forward with the JSON body and parses the response", async () => {
    fetchMock.mockResolvedValue(okJson({ folds: [], mean_sharpe: 0 }));

    const out = await postBacktestWalkForward(WF_REQ);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/backtest/walk-forward");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(WF_REQ);
    expect(out).toEqual({ folds: [], mean_sharpe: 0 });
  });

  it("throws ApiError carrying the backend detail on 422", async () => {
    fetchMock.mockResolvedValue(errJson(422, "insufficient history for the folds"));

    const promise = postBacktestWalkForward(WF_REQ);
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "insufficient history for the folds",
    });
  });
});

describe("postPortfolioMonteCarlo", () => {
  it("POSTs /monte-carlo/portfolio with the JSON body and parses the response", async () => {
    fetchMock.mockResolvedValue(okJson({ confidence_bars: [], degraded: false }));

    const out = await postPortfolioMonteCarlo(MC_REQ);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/monte-carlo/portfolio");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(MC_REQ);
    expect(out).toEqual({ confidence_bars: [], degraded: false });
  });

  it("surfaces ApiError on a degraded-history 422", async () => {
    fetchMock.mockResolvedValue(errJson(422, "insufficient common history"));

    const promise = postPortfolioMonteCarlo(MC_REQ);
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "insufficient common history",
    });
  });
});
