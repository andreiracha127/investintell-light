import { unstable_cache } from "next/cache";

import { serverRequest } from "@/lib/api/server";
import {
  buildFundBackendPath,
  buildFundsScatterBackendPath,
  buildHoldingReverseLookupBackendPath,
  FUND_DOSSIER_REVALIDATE_SECONDS,
  fundResourceCacheKey,
  fundResourceTags,
  holdingReverseLookupCacheKey,
  holdingReverseLookupTags,
  normalizeFundResourceParams,
  normalizeScatterParams,
  scatterCacheKey,
  scatterTags,
  type FundDossierSubresource,
} from "@/lib/funds/dossierQueries";

export async function fetchCachedFundResource<T>(
  resource: FundDossierSubresource,
  instrumentId: string,
  query: Record<string, string | number | null | undefined> = {},
): Promise<T> {
  const params = normalizeFundResourceParams(resource, query);
  const backendPath = buildFundBackendPath(resource, instrumentId, params);
  const getCached = unstable_cache(
    async () => serverRequest<T>(backendPath),
    fundResourceCacheKey(resource, instrumentId, params),
    {
      revalidate: FUND_DOSSIER_REVALIDATE_SECONDS[resource],
      tags: fundResourceTags(resource, instrumentId),
    },
  );
  return getCached();
}

export async function fetchCachedFundsScatter<T>(
  query: Record<string, string | number | null | undefined> = {},
): Promise<T> {
  const params = normalizeScatterParams(query);
  const backendPath = buildFundsScatterBackendPath(params);
  const getCached = unstable_cache(
    async () => serverRequest<T>(backendPath),
    scatterCacheKey(params),
    {
      revalidate: FUND_DOSSIER_REVALIDATE_SECONDS.scatter,
      tags: scatterTags(),
    },
  );
  return getCached();
}

export async function fetchCachedHoldingReverseLookup<T>(
  cusip: string,
): Promise<T> {
  const backendPath = buildHoldingReverseLookupBackendPath(cusip);
  const getCached = unstable_cache(
    async () => serverRequest<T>(backendPath),
    holdingReverseLookupCacheKey(cusip),
    {
      revalidate: FUND_DOSSIER_REVALIDATE_SECONDS["holding-reverse-lookup"],
      tags: holdingReverseLookupTags(cusip),
    },
  );
  return getCached();
}
