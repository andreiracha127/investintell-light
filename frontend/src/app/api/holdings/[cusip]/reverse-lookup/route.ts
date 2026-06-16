import { NextResponse } from "next/server";

import { fetchCachedHoldingReverseLookup } from "@/lib/funds/dossierServer";
import { cacheControlHeader } from "@/lib/funds/dossierQueries";
import { jsonFromDossierError } from "@/lib/funds/dossierRoute";

type RouteContext = {
  params: Promise<{ cusip: string }>;
};

export async function GET(_request: Request, { params }: RouteContext) {
  const { cusip } = await params;
  try {
    const data = await fetchCachedHoldingReverseLookup<unknown>(cusip);
    return NextResponse.json(data, {
      headers: { "Cache-Control": cacheControlHeader("holding-reverse-lookup") },
    });
  } catch (error) {
    return jsonFromDossierError(error);
  }
}
