"use client";

/**
 * Unified shell home — one user type (v4 model). Shows the user's GST
 * accounts from /auth/me (gst_accounts: GSTIN + role + legal_name); the
 * month workspace + deadlines arrive in later tasks (FRONTEND_SPEC §1).
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ShellNav } from "@/components/shared/ShellNav";
import { ApiError, fetchMe, setAccessToken, silentRefresh } from "@/lib/api/client";
import type { MeDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";
import Link from "next/link";

export default function ClientHomePage() {
  const router = useRouter();
  const [me, setMe] = useState<MeDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentFp = "092026"; // default demo period (MMYYYY)

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!(await silentRefresh())) {
          clearSession();
          router.replace("/login");
          return;
        }
        const data = await fetchMe();
        if (!cancelled) setMe(data);
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError && err.status === 401) {
            clearSession();
            router.replace("/login");
            return;
          }
          setError(err instanceof ApiError ? err.message : "failed to load profile");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function signOut() {
    setAccessToken(null);
    clearSession();
    router.push("/login");
  }

  if (me === null && error === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Checking session…
      </div>
    );
  }

  if (error !== null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <ShellNav
        roleLabel="GST Filing"
        userName={me?.user.full_name ?? "…"}
        onSignOut={signOut}
        gstAccounts={me?.gst_accounts ?? []}
      />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <h1 className="text-2xl font-semibold">Your GST accounts</h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Registration month cards and deadlines land with the month workspace.
        </p>
        <div className="mt-8 grid gap-4">
          {me !== null && me.gst_accounts.length > 0 ? (
            me.gst_accounts.map((acc) => (
              <div
                key={acc.gstin}
                className="flex items-center justify-between rounded-lg border border-slate-200 p-4 dark:border-slate-800"
                data-testid="gst-account-card"
              >
                <div>
                  <div className="font-semibold">{acc.legal_name}</div>
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    {acc.gstin}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Link
                    href={`/app/upload/${acc.gstin}/${currentFp}`}
                    className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
                    data-testid="upload-link"
                  >
                    Upload
                  </Link>
                  <Link
                    href={`/app/file/${acc.gstin}/${currentFp}`}
                    className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                    data-testid="documents-link"
                  >
                    Documents
                  </Link>
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    {acc.role}
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No GST accounts linked yet — attach a GSTIN to begin.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
