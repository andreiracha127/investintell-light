import { NextResponse } from "next/server";

import { fetchCachedFundResource } from "@/lib/funds/dossierServer";
import {
  cacheControlHeader,
  normalizeFundResourceParamsFromSearch,
  parseFundSubresource,
} from "@/lib/funds/dossierQueries";
import { jsonFromDossierError } from "@/lib/funds/dossierRoute";

type RouteContext = {
  params: Promise<{ id: string; sub: string }>;
};

export async function GET(request: Request, { params }: RouteContext) {
  const { id, sub } = await params;
  const resource = parseFundSubresource(sub);
  if (resource === null) {
    return NextResponse.json({ detail: `Unsupported fund cache resource: ${sub}` }, { status: 404 });
  }

  const searchParams = new URL(request.url).searchParams;
  const query = normalizeFundResourceParamsFromSearch(resource, searchParams);

  try {
    const data = await fetchCachedFundResource<unknown>(resource, id, query);
    return NextResponse.json(data, {
      headers: { "Cache-Control": cacheControlHeader(resource) },
    });
  } catch (error) {
    return jsonFromDossierError(error);
  }
}
