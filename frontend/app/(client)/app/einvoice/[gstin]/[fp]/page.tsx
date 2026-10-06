"use client";

/**
 * Phase 4 IRN/e-Invoice board — list and generate IRNs for a GSTIN + period.
 */
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import {
  ApiError,
  EInvoiceDto,
  generateIrn,
  listEinvoices,
} from "@/lib/api/client";

export default function EInvoiceBoardPage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const { gstin, fp } = params;

  const [einvoices, setEinvoices] = useState<EInvoiceDto[]>([]);
  const [invoiceId, setInvoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState<EInvoiceDto | null>(null);

  async function load() {
    try {
      const list = await listEinvoices(gstin, fp);
      setEinvoices(list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load IRNs");
    }
  }

  useEffect(() => {
    load();
  }, [gstin, fp]);

  async function generate() {
    if (!invoiceId.trim()) return;
    setBusy(true);
    setError(null);
    setGenerated(null);
    try {
      const res = await generateIrn(invoiceId.trim());
      setGenerated(res);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "IRN generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold">E-Invoices / IRN</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period: <span className="font-mono">{fp}</span>
      </p>

      <div className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800">
        <h2 className="font-semibold">Generate IRN for invoice</h2>
        <div className="mt-4 flex gap-3">
          <input
            type="text"
            value={invoiceId}
            onChange={(e) => setInvoiceId(e.target.value)}
            placeholder="Invoice UUID"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="invoice-id-input"
          />
          <button
            type="button"
            onClick={generate}
            disabled={busy || !invoiceId.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="generate-irn-btn"
          >
            {busy ? "Generating…" : "Generate IRN"}
          </button>
        </div>
      </div>

      {generated !== null && (
        <div className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950">
          <p className="text-sm font-medium text-green-800 dark:text-green-200">IRN generated</p>
          <p className="mt-1 break-all font-mono text-xs text-green-700 dark:text-green-300">{generated.irn}</p>
        </div>
      )}

      <h2 className="mt-8 font-semibold">IRN list</h2>
      <div className="mt-4 grid gap-3">
        {einvoices.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No e-invoices for this period.</p>
        ) : (
          einvoices.map((e) => (
            <div
              key={e.irn}
              className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
              data-testid="einvoice-row"
            >
              <p className="break-all font-mono text-sm">{e.irn}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                ACK: {e.ack_no ?? "—"} · {e.cancelled_at ? `Cancelled ${e.cancelled_at}` : "Active"}
              </p>
            </div>
          ))
        )}
      </div>

      {error !== null && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
