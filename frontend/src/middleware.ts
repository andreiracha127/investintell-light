import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@insforge/sdk/ssr";
import { authGate } from "@/lib/auth/authState";

// Next 15's RequestCookies/ResponseCookies do not structurally match the SDK's
// CookieStore type (the `.set` overloads differ), though they are
// runtime-compatible. Cast to the helper's own parameter types.
type UpdateSessionArg = Parameters<typeof updateSession>[0];

function isInternalPath(pathname: string): boolean {
  return pathname.startsWith("/_next/") || pathname === "/favicon.ico";
}

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });
  const { pathname, search } = request.nextUrl;
  if (isInternalPath(pathname)) return response;

  // Refresh the session cookie. `accessToken` is non-null when the user has a
  // valid (or just-refreshed) session.
  const { accessToken } = await updateSession({
    requestCookies: request.cookies as unknown as UpdateSessionArg["requestCookies"],
    responseCookies: response.cookies as unknown as UpdateSessionArg["responseCookies"],
  });

  const gate = authGate({ pathname, search, authed: accessToken != null });
  if (gate) {
    const redirect = NextResponse.redirect(new URL(gate.redirect, request.url));
    // Preserve the refreshed Set-Cookie headers on the redirect response.
    for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie);
    return redirect;
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/|favicon.ico|api/auth).*)"],
};
