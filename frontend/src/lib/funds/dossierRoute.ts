import { NextResponse } from "next/server";

import { ServerApiError } from "@/lib/api/server";

export function jsonFromDossierError(error: unknown): NextResponse {
  if (error instanceof ServerApiError) {
    return NextResponse.json(error.body ?? { detail: error.message }, {
      status: error.status,
    });
  }

  const message = error instanceof Error ? error.message : "Unexpected fund proxy error";
  return NextResponse.json({ detail: message }, { status: 500 });
}
