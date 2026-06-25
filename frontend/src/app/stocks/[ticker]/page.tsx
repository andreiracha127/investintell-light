import {
  dehydrate,
  HydrationBoundary,
  QueryClient,
} from "@tanstack/react-query";

import { isRangePreset, type RangePreset } from "@/lib/api/client";
import { StockAnalysisView } from "@/components/stocks/StockAnalysisView";
import type { StockQuote } from "@/lib/api/client";
import { serverRequest } from "@/lib/api/server";
import {
  STOCK_DATA_STALE_TIME_MS,
  stockQueryKeys,
} from "@/lib/stocks/queries";

export default async function StockAnalysisPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { ticker } = await params;
  const { range } = await searchParams;
  const symbol = decodeURIComponent(ticker).toUpperCase();
  const initialRange: RangePreset = isRangePreset(range) ? range : "1Y";
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });

  await queryClient
    .prefetchQuery({
      queryKey: stockQueryKeys.quote(symbol),
      queryFn: () =>
        serverRequest<StockQuote>(
          `/stocks/${encodeURIComponent(symbol)}/quote`,
        ),
      staleTime: STOCK_DATA_STALE_TIME_MS,
    })
    .catch(() => undefined);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <StockAnalysisView ticker={symbol} initialRange={initialRange} />
    </HydrationBoundary>
  );
}
