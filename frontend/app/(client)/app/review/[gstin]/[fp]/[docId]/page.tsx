"use client";

/**
 * Review-confirm screen for a single document (Task 7.2).
 * Shows extracted fields + validation flags and lets the user confirm
 * (if clean) or edit and re-confirm.
 */
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  confirmDocument,
  DraftDto,
  getDraft,
  updateDraft,
} from "@/lib/api/client";

function paiseText(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return "—";
  return `₹${(n / 100).toFixed(2)}`;
}

function FieldRow({
  label,
  value,
  confidence,
}: {
  label: string;
  value: React.ReactNode;
  confidence?: number;
}) {
  const display = value ?? "—";
  return (
    <div className="grid grid-cols-3 gap-2 py-2 text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="col-span-2 font-medium">{display}</span>
      {confidence !== undefined && (
        <span className="col-span-3 text-xs">
          confidence: {" "}
          <span
            className={`
              ${confidence >= 0.9 ? "text-green-600" : confidence >= 0.7 ? "text-amber-600" : "text-red-600"}
            `}
          >
            {Math.round(confidence * 100)}%
          </span>
        </span>
      )}
    </div>
  );
}

export default function ReviewPage() {
  const params = useParams<{ gstin: string; fp: string; docId: string }>();
  const router = useRouter();
  const { gstin, fp, docId } = params;

  const [draft, setDraft] = useState<DraftDto | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  async function load() {
    try {
      const data = await getDraft(docId);
      setDraft(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "failed to load draft");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [docId]);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const res = await confirmDocument(docId);
      setSuccess(`Confirmed. Invoice ID: ${res.invoice_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "confirm failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveField(key: string, value: unknown) {
    try {
      const updated = await updateDraft(docId, { [key]: value });
      setDraft(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "update failed");
    }
  }

  if (loading) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading review…</p>
      </main>
    );
  }

  const fields = draft?.fields ?? {};
  const flags = draft?.flags ?? [];
  const dirty = flags.length > 0;

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Review & confirm</h1>
        <button
          type="button"
          onClick={() => router.push(`/app/file/${gstin}/${fp}`)}
          className="text-sm text-slate-500 hover:underline"
        >
          ← Back to documents
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period:{" "}
        <span className="font-mono">{fp}</span> · Doc:{" "}
        <span className="font-mono">{docId}</span>
      </p>

      {error !== null && (
        <p
          className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
          role="alert"
          data-testid="review-error"
        >
          {error}
        </p>
      )}

      {success !== null && (
        <div
          className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950"
          data-testid="review-success"
        >
          <p className="text-sm font-medium text-green-800 dark:text-green-200">
            {success}
          </p>
          <button
            type="button"
            onClick={() => router.push(`/app/returns/${gstin}/${fp}`)}
            className="mt-3 rounded-md bg-green-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-800"
            data-testid="go-to-returns"
          >
            Download returns →
          </button>
        </div>
      )}

      {flags.length > 0 && (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950">
          <h2 className="text-sm font-semibold text-amber-800 dark:text-amber-200">
            Validation flags
          </h2>
          <ul className="mt-2 list-inside list-disc text-sm text-amber-700 dark:text-amber-300">
            {flags.map((f, i) => (
              <li key={i}>
                {f.rule} ({f.severity}): {f.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {draft !== null && (
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
            <h2 className="font-semibold">Parties</h2>
            <FieldRow
              label="Supplier GSTIN"
              value={String(fields.supplier_gstin ?? "")}
              confidence={draft.confidence.supplier_gstin}
            />
            <FieldRow
              label="Buyer GSTIN"
              value={String(fields.buyer_gstin ?? "")}
              confidence={draft.confidence.buyer_gstin}
            />
          </div>

          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
            <h2 className="font-semibold">Invoice</h2>
            <FieldRow label="Invoice no" value={String(fields.invoice_no ?? "")} confidence={draft.confidence.invoice_no} />
            <FieldRow label="Date" value={String(fields.invoice_date ?? "")} confidence={draft.confidence.invoice_date} />
            <FieldRow label="POS" value={String(fields.place_of_supply ?? "")} confidence={draft.confidence.place_of_supply} />
            <FieldRow label="Inter-state" value={fields.is_inter_state ? "Yes" : "No"} />
            <FieldRow label="Reverse charge" value={fields.rchrg ? "Yes" : "No"} />
            <FieldRow label="Type" value={String(fields.inv_typ ?? "")} />
          </div>

          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
            <h2 className="font-semibold">Tax totals</h2>
            <FieldRow label="Taxable" value={paiseText(fields.taxable_value_paise)} />
            <FieldRow label="Total" value={paiseText(fields.total_value_paise)} />
            <FieldRow label="CGST" value={paiseText(fields.cgst_paise)} />
            <FieldRow label="SGST" value={paiseText(fields.sgst_paise)} />
            <FieldRow label="IGST" value={paiseText(fields.igst_paise)} />
            <FieldRow label="CESS" value={paiseText(fields.cess_paise)} />
          </div>

          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
            <h2 className="font-semibold">Derived</h2>
            <FieldRow label="Supply type" value={String(draft.derived.supply_type ?? "")} />
            <FieldRow label="Period" value={String(draft.derived.fp ?? "")} />
            <FieldRow label="Auto-confirm" value={String(draft.auto_confirm ?? "")} />
          </div>
        </div>
      )}

      <div className="mt-8 flex items-center gap-4">
        <button
          type="button"
          onClick={confirm}
          disabled={busy || dirty || draft === null}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          data-testid="confirm-document"
        >
          {busy ? "Confirming…" : "Confirm"}
        </button>
        <p className="text-sm text-slate-500">
          {dirty
            ? "Resolve validation flags before confirming."
            : "All checks passed — confirm to add to the ledger."}
        </p>
      </div>

      {draft !== null && (
        <div className="mt-8 rounded-xl border border-slate-200 p-5 dark:border-slate-800">
          <h2 className="font-semibold">Quick edit (demo)</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs">Invoice no</label>
              <input
                type="text"
                defaultValue={String(fields.invoice_no ?? "")}
                onBlur={(e) => saveField("invoice_no", e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <div>
              <label className="block text-xs">Total value (paise)</label>
              <input
                type="number"
                defaultValue={String(fields.total_value_paise ?? 0)}
                onBlur={(e) => saveField("total_value_paise", Number(e.target.value))}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
