import { NextResponse } from "next/server";
import { createServerClient } from "@insforge/sdk/ssr";

export async function POST() {
  const client = createServerClient();
  await client.auth.signOut();
  const response = NextResponse.json({ ok: true });
  response.cookies.delete("insforge_access_token");
  response.cookies.delete("insforge_refresh_token");
  return response;
}
