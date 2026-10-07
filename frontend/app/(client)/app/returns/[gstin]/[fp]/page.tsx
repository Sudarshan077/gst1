"use client";

/**
 * Returns / output page for a GSTIN + period. Lets the user download the
 * generated GSTR-1 and GSTR-3B JSON payloads built from confirmed invoices.
 */
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  getGstr1Export,
  getGstr3bExport,
  getMonthSummary,
  MonthSummaryDto,
} from "@/lib/api/client";

function downloadJson(name: string, payload: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function ReturnsPage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const { gstin, fp } = params;

  const [summary, setSummary] = useState<MonthSummaryDto | null>(null);
  const [gstr1, setGstr1] = useState<Record<string, unknown> | null>(null);
  const [gstr3b, setGstr3b] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [s, r1, r3b] = await Promise.all([
          getMonthSummary(gstin, fp),
          getGstr1Export(gstin, fp),
          getGstr3bExport(gstin, fp),
        ]);
        if (!cancelled) {
          setSummary(s);
          setGstr1(r1);
          setGstr3b(r3b);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [gstin, fp]);

  if (loading) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading returns…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-8">
      <h1 className="text-2xl font-semibold">Returns output</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period:{" "}
        <span className="font-mono">{fp}</span>
      </p>

      {error !== null && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {summary !== null && (
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-xs text-slate-500">Confirmed invoices</p>
            <p className="text-2xl font-semibold">{summary.confirmed_count}</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-xs text-slate-500">Taxable value</p>
            <p className="text-2xl font-semibold">₹{(summary.total_taxable_minor / 100).toFixed(2)}</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-xs text-slate-500">Status</p>
            <p className="text-2xl font-semibold">{summary.status}</p>
          </div>
        </div>
      )}

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="font-semibold">GSTR-1</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Outward supply JSON from confirmed ledger.
          </p>
          <button
            type="button"
            onClick={() => gstr1 && downloadJson(`GSTR1-${gstin}-${fp}.json`, gstr1)}
            disabled={gstr1 === null}
            className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="download-gstr1"
          >
            Download GSTR-1 JSON
          </button>
        </div>

        <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="font-semibold">GSTR-3B</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Summary return JSON from confirmed ledger.
          </p>
          <button
            type="button"
            onClick={() => gstr3b && downloadJson(`GSTR3B-${gstin}-${fp}.json`, gstr3b)}
            disabled={gstr3b === null}
            className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="download-gstr3b"
          >
            Download GSTR-3B JSON
          </button>
        </div>
      </div>
    </main>
  );
}
