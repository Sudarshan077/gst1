/**
 * Routing-only guard — FRONTEND_SPECIFICATION.md §4: middleware handles
 * routing, never authorization (the server is the authority). A single
 * gst_session cookie marks a logged-in browser; no role split exists in the
 * unified v4 model (one user type; GSTIN attachment grants access).
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/register"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const authed = request.cookies.has("gst_session");

  if (isPublic(pathname)) {
    if (authed) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }

  if (!authed) {
    // navigation sugar only — the cookie is client-writable, so shells
    // re-verify via silentRefresh() + /auth/me before rendering data.
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // everything except Next internals and the proxied API
    "/((?!api/v1|_next/static|_next/image|favicon.ico).*)",
  ],
};