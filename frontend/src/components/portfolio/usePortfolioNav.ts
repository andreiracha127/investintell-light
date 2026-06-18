"use client";

/**
 * Shared hook: reconstruct a portfolio's synthetic NAV from the current
 * holdings' real price histories. One history query per holding (funds by
 * instrument_id → NAV/line series; stocks by ticker → OHLC close), fetched at
 * MAX range and cached under a stable key so the Overview mini-NAV and the
 * Performance tab share the same fetches.
 *
 * The arithmetic lives in the pure `lib/portfolio/performance` module; this hook
 * only wires the fetches into it.
 */
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  fetchFundTimeseries,
  fetchStockTimeseries,
  type PortfolioOverview,
} from "@/lib/api/client";
import {
  pricePointsFromLine,
  pricePointsFromOhlc,
  reconstructNav,
  type HoldingSeries,
  type NavReconstruction,
} from "@/lib/portfolio/performance";
import { retryPolicy } from "@/components/screener/shared";

export interface PortfolioNav {
  holdings: HoldingSeries[];
  recon: NavReconstruction;
  isLoading: boolean;
  isError: boolean;
}

export function usePortfolioNav(overview: PortfolioOverview): PortfolioNav {
  const positions = overview.positions;
  const cash = overview.aggregates.cash;

  const results = useQueries({
    queries: positions.map((p) => {
      const fundId = p.instrument_id;
      return {
        queryKey: ["portfolio-perf-history", fundId ? `fund:${fundId}` : `stock:${p.ticker}`],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          fundId
            ? fetchFundTimeseries(fundId, "MAX", signal)
            : fetchStockTimeseries(p.ticker, "MAX", signal),
        staleTime: 5 * 60_000,
        retry: retryPolicy,
      };
    }),
  });

  const navSig = results.map((r) => r.dataUpdatedAt).join("|");
  const holdings = useMemo<HoldingSeries[]>(
    () =>
      positions.map((p, i) => {
        const data = results[i]?.data;
        let points: Array<[number, number]> = [];
        if (data) {
          if ("ohlc" in data) points = pricePointsFromOhlc(data.ohlc);
          else if ("series" in data) points = pricePointsFromLine(data.series);
        }
        return {
          ticker: p.ticker,
          name: p.name ?? p.ticker,
          quantity: p.quantity,
          points,
        };
      }),
    // navSig captures query data changes; positions the holding set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [navSig, positions],
  );

  const recon = useMemo(() => reconstructNav(holdings, cash), [holdings, cash]);

  return {
    holdings,
    recon,
    isLoading: results.some((r) => r.isPending),
    isError: results.some((r) => r.isError),
  };
}
