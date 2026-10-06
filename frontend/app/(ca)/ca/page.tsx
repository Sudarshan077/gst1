"use client";

/**
 * CA shell home — client roster with live /auth/me data.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useMemo } from "react";

import { ShellNav } from "@/components/shared/ShellNav";
import { ApiError, fetchMe, setAccessToken, silentRefresh, listGstAccounts, GstAccountDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

interface Me {
  user: { full_name: string; totp_enabled: boolean };
  firm: string | null;
}

export default function CaHomePage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [gstAccounts, setGstAccounts] = useState<GstAccountDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!(await silentRefresh())) {
          clearSession();
          router.replace("/login");
          return;
        }
        const [meData, gstData] = await Promise.all([fetchMe(), listGstAccounts()]);
        if (!cancelled) {
            setMe(meData);
            setGstAccounts(gstData);
        }
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

  const filteredAccounts = useMemo(() => {
    return gstAccounts.filter(acc => 
        acc.legal_name.toLowerCase().includes(search.toLowerCase()) || 
        acc.gstin.toLowerCase().startsWith(search.toLowerCase())
    );
  }, [gstAccounts, search]);

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
        roleLabel="CA firm"
        userName={me?.user.full_name ?? "…"}
        onSignOut={signOut}
      />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold">Client roster</h1>
            <input 
                type="text"
                placeholder="Search by name or GSTIN..."
                className="rounded-lg border p-2 text-sm"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
            />
        </div>
        
        <div className="mt-8 grid gap-4">
            {filteredAccounts.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                        No clients matching &ldquo;{search}&rdquo; — firm id: {me?.firm ?? "—"}
                    </p>
                </div>
            ) : (
                filteredAccounts.map(acc => (
                    <Link key={acc.gstin} href={`/${acc.gstin}`} className="flex items-center justify-between rounded-lg border p-4 hover:border-indigo-400">
                        <div>
                            <div className="font-semibold">{acc.legal_name}</div>
                            <div className="text-sm text-slate-500">{acc.gstin}</div>
                        </div>
                        <div className="text-sm">{acc.role}</div>
                    </Link>
                ))
            )}
        </div>
      </main>
    </div>
  );
}
