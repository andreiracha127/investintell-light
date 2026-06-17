import { NextResponse } from "next/server";
import { createServerClient, setAuthCookies } from "@insforge/sdk/ssr";

function authErrorStatus(statusCode: unknown): number {
  return typeof statusCode === "number" && statusCode >= 200 && statusCode <= 599
    ? statusCode
    : 401;
}

export async function POST(request: Request) {
  let body: { email: string; password: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "BAD_REQUEST", message: "Invalid request body" }, { status: 400 });
  }
  const client = createServerClient();
  const { data, error } = await client.auth.signInWithPassword(body);

  if (error || !data?.accessToken) {
    return NextResponse.json(
      { error: error?.error ?? "AUTH_UNAUTHORIZED", message: error?.message ?? "Sign in failed" },
      { status: authErrorStatus(error?.statusCode) },
    );
  }

  const response = NextResponse.json({ user: data.user });
  setAuthCookies(response.cookies, {
    accessToken: data.accessToken,
    refreshToken: data.refreshToken,
  });
  return response;
}
