"use client";

/**
 * Phase 4 IRN/e-Invoice board — list confirmed outward invoices for a
 * GSTIN + period and generate IRNs for them.
 *
 * Audit fix (CA partner persona): the board previously asked the user to
 * paste a raw database Invoice UUID. CAs think in Invoice Numbers, so the
 * board now lists human-readable invoices (Invoice No, Date, Buyer GSTIN,
 * Total) with a 1-click [Generate IRN] per row. The internal Invoice.id is
 * passed to POST /invoices/{id}/irn but never surfaced to the user.
 */
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import {
  ApiError,
  EInvoiceDto,
  InvoiceDto,
  generateIrn,
  listEinvoices,
  listInvoices,
} from "@/lib/api/client";

/** Integer paise → rupee string with Indian grouping, e.g. ₹1,18,000.00. */
function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function EInvoiceBoardPage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const { gstin, fp } = params;

  const [invoices, setInvoices] = useState<InvoiceDto[]>([]);
  const [einvoices, setEinvoices] = useState<EInvoiceDto[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState<EInvoiceDto | null>(null);

  async function load() {
    try {
      const [inv, irnList] = await Promise.all([
        listInvoices(gstin, fp),
        listEinvoices(gstin, fp),
      ]);
      setInvoices(inv);
      setEinvoices(irnList);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load IRNs");
    }
  }

  useEffect(() => {
    load();
  }, [gstin, fp]);

  async function generate(invoiceId: string) {
    setBusyId(invoiceId);
    setError(null);
    setGenerated(null);
    try {
      const res = await generateIrn(invoiceId);
      setGenerated(res);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "IRN generation failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold">E-Invoices / IRN</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period: <span className="font-mono">{fp}</span>
      </p>

      {error !== null && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300" role="alert">
          {error}
        </p>
      )}

      {generated !== null && (
        <div className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950">
          <p className="text-sm font-medium text-green-800 dark:text-green-200">IRN generated</p>
          <p className="mt-1 break-all font-mono text-xs text-green-700 dark:text-green-300">{generated.irn}</p>
        </div>
      )}

      <h2 className="mt-8 font-semibold">Confirmed invoices</h2>
      <div className="mt-4 overflow-x-auto" data-testid="einvoice-invoices-table">
        {invoices.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No confirmed invoices for this period.
          </p>
        ) : (
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
                <th className="py-2 pr-4 font-medium">Invoice No</th>
                <th className="py-2 pr-4 font-medium">Date</th>
                <th className="py-2 pr-4 font-medium">Buyer GSTIN</th>
                <th className="py-2 pr-4 font-medium text-right">Total</th>
                <th className="py-2 font-medium">IRN</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const alreadyDone = inv.irn !== null;
                return (
                  <tr
                    key={inv.id}
                    className="border-b border-slate-100 dark:border-slate-800"
                    data-testid="einvoice-invoice-row"
                  >
                    <td className="py-2 pr-4 font-medium">{inv.invoice_no}</td>
                    <td className="py-2 pr-4">{inv.invoice_date}</td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {inv.buyer_gstin ?? "—"}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {rupees(inv.total_value_minor)}
                    </td>
                    <td className="py-2">
                      {alreadyDone ? (
                        <span
                          className="inline-block max-w-[180px] truncate align-middle font-mono text-xs text-green-700 dark:text-green-300"
                          title={inv.irn ?? ""}
                          data-testid="invoice-irn-badge"
                        >
                          {inv.irn_status === "CANCELLED"
                            ? "Cancelled"
                            : "Generated ✓"}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => generate(inv.id)}
                          disabled={busyId !== null}
                          className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                          data-testid="generate-irn-btn"
                        >
                          {busyId === inv.id ? "Generating…" : "Generate IRN"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

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
    </main>
  );
}
