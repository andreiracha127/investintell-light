import type { Metadata } from "next";
import {
  dehydrate,
  HydrationBoundary,
  QueryClient,
} from "@tanstack/react-query";

import { FundProfileView } from "@/components/funds/FundProfileView";
import type {
  FundAnalysis,
  FundFactors,
  FundHoldingsTop,
  FundPeers,
  FundProfile,
  FundRiskTimeseries,
  FundStyleDrift,
  FundTimeseries,
} from "@/lib/api/client";
import { fetchCachedFundResource } from "@/lib/funds/dossierServer";
import {
  dossierQueryKeys,
  FUND_DOSSIER_DEFAULTS,
  FUND_DOSSIER_STALE_TIME_MS,
} from "@/lib/funds/dossierQueries";

export const metadata: Metadata = {
  title: "Fund profile — Investintell Light",
};

export default async function FundProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const instrumentId = decodeURIComponent(id);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });

  await Promise.all([
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.profile(instrumentId),
      queryFn: () => fetchCachedFundResource<FundProfile>("profile", instrumentId),
      staleTime: FUND_DOSSIER_STALE_TIME_MS.profile,
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.timeseries(instrumentId, {
        range: FUND_DOSSIER_DEFAULTS.range,
      }),
      queryFn: () =>
        fetchCachedFundResource<FundTimeseries>("timeseries", instrumentId, {
          range: FUND_DOSSIER_DEFAULTS.range,
        }),
      staleTime: FUND_DOSSIER_STALE_TIME_MS.timeseries,
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.analysis(instrumentId, {
        range: FUND_DOSSIER_DEFAULTS.range,
        window: FUND_DOSSIER_DEFAULTS.analysisWindow,
      }),
      queryFn: () =>
        fetchCachedFundResource<FundAnalysis>("analysis", instrumentId, {
          range: FUND_DOSSIER_DEFAULTS.range,
          window: FUND_DOSSIER_DEFAULTS.analysisWindow,
        }),
      staleTime: FUND_DOSSIER_STALE_TIME_MS.analysis,
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.riskTimeseries(instrumentId),
      queryFn: () =>
        fetchCachedFundResource<FundRiskTimeseries>(
          "risk-timeseries",
          instrumentId,
        ),
      staleTime: FUND_DOSSIER_STALE_TIME_MS["risk-timeseries"],
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.holdingsTop(instrumentId, {
        limit: FUND_DOSSIER_DEFAULTS.holdingsTopLimit,
      }),
      queryFn: () =>
        fetchCachedFundResource<FundHoldingsTop>("holdings-top", instrumentId, {
          limit: FUND_DOSSIER_DEFAULTS.holdingsTopLimit,
        }),
      staleTime: FUND_DOSSIER_STALE_TIME_MS["holdings-top"],
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.peers(instrumentId, {
        limit: FUND_DOSSIER_DEFAULTS.peersLimit,
      }),
      queryFn: () =>
        fetchCachedFundResource<FundPeers>("peers", instrumentId, {
          limit: FUND_DOSSIER_DEFAULTS.peersLimit,
        }),
      staleTime: FUND_DOSSIER_STALE_TIME_MS.peers,
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.factors(instrumentId),
      queryFn: () => fetchCachedFundResource<FundFactors>("factors", instrumentId),
      staleTime: FUND_DOSSIER_STALE_TIME_MS.factors,
    }),
    queryClient.prefetchQuery({
      queryKey: dossierQueryKeys.styleDrift(instrumentId, {
        quarters: FUND_DOSSIER_DEFAULTS.styleDriftQuarters,
      }),
      queryFn: () =>
        fetchCachedFundResource<FundStyleDrift>("style-drift", instrumentId, {
          quarters: FUND_DOSSIER_DEFAULTS.styleDriftQuarters,
        }),
      staleTime: FUND_DOSSIER_STALE_TIME_MS["style-drift"],
    }),
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FundProfileView instrumentId={instrumentId} />
    </HydrationBoundary>
  );
}
