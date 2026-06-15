import { NextResponse } from "next/server";

import { fetchCachedFundsScatter } from "@/lib/funds/dossierServer";
import {
  cacheControlHeader,
  normalizeScatterParams,
} from "@/lib/funds/dossierQueries";
import { jsonFromDossierError } from "@/lib/funds/dossierRoute";

export async function GET(request: Request) {
  const searchParams = new URL(request.url).searchParams;
  const query = normalizeScatterParams({ limit: searchParams.get("limit") });

  try {
    const data = await fetchCachedFundsScatter<unknown>(query);
    return NextResponse.json(data, {
      headers: { "Cache-Control": cacheControlHeader("scatter") },
    });
  } catch (error) {
    return jsonFromDossierError(error);
  }
}
