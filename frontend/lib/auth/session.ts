/**
 * Session store (module scope, client-side): access JWT in memory only
 * (SECURITY §6: no tokens in localStorage). A single routing cookie marks an
 * authenticated session for the middleware routing guard; no role split exists
 * in the unified v4 model (FRONTEND_SPECIFICATION.md §4).
 */

const SESSION_COOKIE = "gst_session";

export function setSessionCookie(): void {
  // routing hint only — never used for authorization
  document.cookie = `${SESSION_COOKIE}=1; path=/; samesite=lax; max-age=${7 * 24 * 3600}`;
}

export function readSessionCookie(): boolean {
  return document.cookie
    .split("; ")
    .some((c) => c.startsWith(`${SESSION_COOKIE}=`));
}

export function clearSession(): void {
  document.cookie = `${SESSION_COOKIE}=; path=/; max-age=0`;
}