"use client";

/**
 * CA roster view — GST accounts list with live data. Unified v4 model:
 * same one user type as /app; this route is a roster convenience page.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useMemo } from "react";

import { ShellNav } from "@/components/shared/ShellNav";
import { ApiError, fetchMe, setAccessToken, silentRefresh, listGstAccounts, GstAccountDto } from "@/lib/api/client";
import type { MeDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

export default function CaHomePage() {
  const router = useRouter();
  const [me, setMe] = useState<MeDto | null>(null);
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

  function exportRosterCsv() {
    const headers = ["Legal Name", "Trade Name", "GSTIN", "PAN", "State Code", "Filing Scheme", "IRN Applicable"];
    const rows = gstAccounts.map(a => [
      `"${a.legal_name.replace(/"/g, '""')}"`,
      `"${(a.trade_name || "").replace(/"/g, '""')}"`,
      a.gstin,
      a.pan,
      a.state_code,
      a.filing_scheme,
      a.irn_applicable ? "Yes" : "No"
    ]);
    const csvContent = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ca_client_roster_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

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
        {/* CA Executive KPI Cards */}
        <div className="grid gap-4 sm:grid-cols-3 mb-6" data-testid="ca-kpi-cards">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Total Managed Clients</p>
            <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-white" data-testid="kpi-total-clients">{gstAccounts.length}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Regular Monthly Filers</p>
            <p className="mt-1 text-2xl font-bold text-indigo-600 dark:text-indigo-400" data-testid="kpi-monthly-filers">
              {gstAccounts.filter(a => a.filing_scheme.includes("REGULAR")).length}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">E-Invoicing (IRN) Applicable</p>
            <p className="mt-1 text-2xl font-bold text-emerald-600 dark:text-emerald-400" data-testid="kpi-irn-clients">
              {gstAccounts.filter(a => a.irn_applicable).length}
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Client roster</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">Multi-client compliance management and statutory monitoring</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={exportRosterCsv}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 transition-colors"
              data-testid="export-roster-csv-btn"
            >
              📥 Export Roster (CSV)
            </button>
            <input 
              type="text"
              placeholder="Search by name or GSTIN..."
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="ca-search-input"
            />
          </div>
        </div>
        
        <div className="mt-8 grid gap-4">
            {filteredAccounts.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                        No GST accounts matching &ldquo;{search}&rdquo;
                    </p>
                </div>
            ) : (
                filteredAccounts.map(acc => (
                    <Link key={acc.gstin} href={`/app/businesses/${acc.gstin}`} className="flex items-center justify-between rounded-lg border p-4 hover:border-indigo-400">
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
