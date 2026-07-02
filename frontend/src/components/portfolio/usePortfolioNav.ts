"use client";

/**
 * Shared hook over the persisted portfolio NAV series.
 *
 * The backend worker materializes daily NAV from the real transaction ledger
 * into `portfolio_nav_daily`; the UI only reads that DB-first series.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchPortfolioNav,
  type PortfolioNav as PortfolioNavResponse,
} from "@/lib/api/client";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import type { NavReconstruction } from "@/lib/portfolio/performance";
import { retryPolicy } from "@/components/screener/shared";

export interface PortfolioNav {
  recon: NavReconstruction;
  response: PortfolioNavResponse | null;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}

const EMPTY_RECON: NavReconstruction = {
  nav: [],
  navIndex: [],
  startTs: 0,
  endTs: 0,
};

function reconstructFromPersisted(
  response: PortfolioNavResponse | undefined,
): NavReconstruction {
  const points = response?.points ?? [];
  if (points.length === 0) return EMPTY_RECON;
  const navIndex = points.map(
    (point) => [dateToUtcMs(point.date), point.nav] as [number, number],
  );
  return {
    // The persisted `nav` field is an index rebased to 100, not raw dollars.
    nav: navIndex,
    navIndex,
    startTs: navIndex[0]![0],
    endTs: navIndex[navIndex.length - 1]![0],
  };
}

export function usePortfolioNav(portfolioId: number | null | undefined): PortfolioNav {
  const query = useQuery({
    queryKey: ["portfolio-nav", portfolioId],
    queryFn: ({ signal }) => {
      if (portfolioId === null || portfolioId === undefined) {
        throw new Error("Portfolio id is required to load NAV.");
      }
      return fetchPortfolioNav(portfolioId, {}, signal);
    },
    enabled: portfolioId !== null && portfolioId !== undefined,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  const recon = useMemo(
    () => reconstructFromPersisted(query.data),
    [query.data],
  );

  return {
    recon,
    response: query.data ?? null,
    isLoading: query.isPending,
    isError: query.isError,
    refetch: () => {
      void query.refetch();
    },
  };
}
