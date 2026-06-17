import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@insforge/sdk/ssr";

// Next 15's RequestCookies/ResponseCookies do not structurally match the SDK's
// CookieStore type (the `.set` overloads differ), though they are
// runtime-compatible. Cast to the helper's own parameter types.
type UpdateSessionArg = Parameters<typeof updateSession>[0];

function isPublicPath(pathname: string): boolean {
  return pathname === "/login" || pathname === "/funds" || pathname.startsWith("/funds/");
}

function isInternalPath(pathname: string): boolean {
  return pathname.startsWith("/_next/") || pathname === "/favicon.ico";
}

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });
  if (isInternalPath(request.nextUrl.pathname)) return response;
  if (isPublicPath(request.nextUrl.pathname)) return response;
  await updateSession({
    requestCookies: request.cookies as unknown as UpdateSessionArg["requestCookies"],
    responseCookies: response.cookies as unknown as UpdateSessionArg["responseCookies"],
  });
  return response;
}

export const config = {
  matcher: ["/((?!_next/|favicon.ico|api/auth).*)"],
};
