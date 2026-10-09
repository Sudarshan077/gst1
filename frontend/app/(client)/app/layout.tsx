"use client";

/**
 * Shared client shell layout — PHASE10_BUG_SWEEP_FIXES.md §10.2.
 *
 * Renders <ShellNav> exactly ONCE for every route under (client)/app, so the
 * header, role chip, user chip, GSTIN switcher and Sign out are present on the
 * workspace routes that previously had no shared chrome (upload / returns /
 * review / einvoice / file) — and are no longer duplicated per page on
 * dashboard / profile / settings / businesses / businesses[gstin] / itc
 * (no double header). FRONTEND_SPECIFICATION.md §3.11.
 *
 * On mount it silently refreshes the session and reads /auth/me once to feed
 * userName + gstAccounts into the nav. The nav is rendered only once that
 * resolve completes, so the GSTIN-scoped nav links never expose their
 * empty-account fallback (the old pages showed no nav until their own fetch
 * resolved — this preserves that guarantee). A dead session clears the routing
 * cookie and redirects to /login (FRONTEND_SPECIFICATION.md §4: the server
 * stays the authority; the cookie is a routing hint only). Pages still own
 * their own data fetches and loading/error states; this layout owns the chrome.
 */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ShellContext } from "@/components/shared/ShellContext";
import { ShellNav } from "@/components/shared/ShellNav";
import {
  ApiError,
  fetchMe,
  setAccessToken,
  silentRefresh,
} from "@/lib/api/client";
import type { GstinRefDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

export default function ClientAppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [userName, setUserName] = useState("…");
  const [gstAccounts, setGstAccounts] = useState<GstinRefDto[]>([]);
  // False until the /auth/me resolve settles: the nav (and its links) render
  // only with real account data, never the empty-account fallback.
  const [navReady, setNavReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!(await silentRefresh())) {
          clearSession();
          router.replace("/login");
          return;
        }
        const me = await fetchMe();
        if (cancelled) return;
        setUserName(me.user.full_name);
        setGstAccounts(me.gst_accounts);
        setNavReady(true);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        // Non-401 failure: still render the nav with defaults so each page can
        // surface its own inline error (FRONTEND_SPEC §4) without a blank shell.
        setNavReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const signOut = useCallback(() => {
    setAccessToken(null);
    clearSession();
    router.push("/login");
  }, [router]);

  const shell = useMemo(
    () => ({ userName, gstAccounts, setUserName, setGstAccounts }),
    [userName, gstAccounts],
  );

  return (
    <ShellContext.Provider value={shell}>
      <div className="flex min-h-screen flex-col">
        {navReady ? (
          <ShellNav
            roleLabel="GST Filing"
            userName={userName}
            onSignOut={signOut}
            gstAccounts={gstAccounts}
          />
        ) : null}
        {children}
      </div>
    </ShellContext.Provider>
  );
}
