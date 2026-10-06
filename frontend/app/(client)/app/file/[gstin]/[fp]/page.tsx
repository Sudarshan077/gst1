"use client";

/**
 * Phase 4 filing hub — GSP direct filing for GSTR-1 and GSTR-3B (sandbox).
 * Accessible from the unified shell; GSTIN + period are route params.
 */
import { useState } from "react";
import { useParams } from "next/navigation";

import {
  ApiError,
  fileGstr1ViaGsp,
  fileGstr3bViaGsp,
  GspFileResult,
} from "@/lib/api/client";

export default function FilingHubPage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const { gstin, fp } = params;

  const [busy, setBusy] = useState<"gstr1" | "gstr3b" | null>(null);
  const [result, setResult] = useState<GspFileResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fileGstr1() {
    setBusy("gstr1");
    setError(null);
    setResult(null);
    try {
      const res = await fileGstr1ViaGsp(gstin, fp);
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "GSTR-1 filing failed");
    } finally {
      setBusy(null);
    }
  }

  async function fileGstr3b() {
    setBusy("gstr3b");
    setError(null);
    setResult(null);
    try {
      const res = await fileGstr3bViaGsp(gstin, fp);
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "GSTR-3B filing failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold">Direct filing</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period: <span className="font-mono">{fp}</span>
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="font-semibold">GSTR-1</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            File outward return via GSP sandbox.
          </p>
          <button
            type="button"
            onClick={fileGstr1}
            disabled={busy !== null}
            className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="file-gstr1-btn"
          >
            {busy === "gstr1" ? "Filing…" : "File GSTR-1"}
          </button>
        </div>

        <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="font-semibold">GSTR-3B</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            File summary return via GSP sandbox.
          </p>
          <button
            type="button"
            onClick={fileGstr3b}
            disabled={busy !== null}
            className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="file-gstr3b-btn"
          >
            {busy === "gstr3b" ? "Filing…" : "File GSTR-3B"}
          </button>
        </div>
      </div>

      {result !== null && (
        <div
          className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950"
          data-testid="file-result"
        >
          <p className="text-sm font-medium text-green-800 dark:text-green-200">
            {result.status}
          </p>
          <p className="mt-1 font-mono text-xs text-green-700 dark:text-green-300">
            Ref: {result.ref_id} · ACK: {result.ack_no}
          </p>
        </div>
      )}

      {error !== null && (
        <p
          className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
          role="alert"
          data-testid="file-error"
        >
          {error}
        </p>
      )}
    </main>
  );
}
