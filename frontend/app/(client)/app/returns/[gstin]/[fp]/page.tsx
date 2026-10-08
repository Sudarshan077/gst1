"use client";

/**
 * Returns workspace for a GSTIN + period (task 8.9, additively reworked from
 * the 7.2 download-only page — PHASE8_PRODUCT_COMPLETENESS.md §3.8.9):
 *
 *   1. Generate — POST /returns/generate (the 8.4 idempotent prepare→generate
 *      orchestration for GSTR-1 and GSTR-3B).
 *   2. Format picker — JSON (client blob) or Excel (.xlsx rendered
 *      server-side by the backend from the same payload).
 *   3. HSN summary table (GET /gstr1/hsn-summary).
 *   4. Pre-filing validation checklist (GET /returns/validation): blocking
 *      findings gate the downloads, warnings render as amber rows.
 *
 * The existing download-gstr1 / download-gstr3b testids and JSON downloads
 * survive untouched (the 7.2 spec depends on them). Money is integer paise
 * from the API; rupee conversion happens only at render (FRONTEND_SPEC §4).
 */
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  downloadReturnXlsx,
  generateReturns,
  getGstr1Export,
  getGstr3bExport,
  getHsnSummary,
  getMonthSummary,
  getReturnsValidation,
  HsnSummaryResult,
  MonthSummaryDto,
  ReturnsGenerateResult,
  ReturnsValidationResult,
} from "@/lib/api/client";

type ExportFormat = "json" | "xlsx";

/** Paise → "₹1,23,456.78" (Indian grouping) — render-only conversion. */
function rupees(paise: number): string {
  const value = paise / 100;
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
  return `₹${formatted}`;
}

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

  // 8.9 workspace state.
  const [format, setFormat] = useState<ExportFormat>("json");
  const [generating, setGenerating] = useState(false);
  const [generateResult, setGenerateResult] =
    useState<ReturnsGenerateResult | null>(null);
  const [hsn, setHsn] = useState<HsnSummaryResult | null>(null);
  const [validation, setValidation] = useState<ReturnsValidationResult | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [downloadingForm, setDownloadingForm] = useState<
    "gstr1" | "gstr3b" | null
  >(null);

  const refreshWorkspace = useCallback(async () => {
    const [hsnData, validationData] = await Promise.all([
      getHsnSummary(gstin, fp),
      getReturnsValidation(gstin, fp),
    ]);
    setHsn(hsnData);
    setValidation(validationData);
  }, [gstin, fp]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [s, r1, r3b, hsnData, validationData] = await Promise.all([
          getMonthSummary(gstin, fp),
          getGstr1Export(gstin, fp),
          getGstr3bExport(gstin, fp),
          getHsnSummary(gstin, fp),
          getReturnsValidation(gstin, fp),
        ]);
        if (!cancelled) {
          setSummary(s);
          setGstr1(r1);
          setGstr3b(r3b);
          setHsn(hsnData);
          setValidation(validationData);
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

  async function handleGenerate() {
    setGenerating(true);
    setActionError(null);
    try {
      const result = await generateReturns(gstin, fp);
      setGenerateResult(result);
      await refreshWorkspace();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "generate failed");
    } finally {
      setGenerating(false);
    }
  }

  async function handleDownload(form: "gstr1" | "gstr3b") {
    setActionError(null);
    try {
      if (format === "xlsx") {
        setDownloadingForm(form);
        await downloadReturnXlsx(gstin, fp, form);
      } else {
        const payload = form === "gstr1" ? gstr1 : gstr3b;
        if (payload === null) return;
        downloadJson(`${form.toUpperCase()}-${gstin}-${fp}.json`, payload);
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "download failed");
    } finally {
      setDownloadingForm(null);
    }
  }

  const blocking = validation?.blocking ?? [];
  const warnings = validation?.warnings ?? [];
  const blocked = blocking.length > 0;

  if (loading) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading returns…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-8">
      <h1 className="text-2xl font-semibold">Returns workspace</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period:{" "}
        <span className="font-mono">{fp}</span>
      </p>

      {error !== null && (
        <p
          className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
          data-testid="returns-error"
        >
          {error}
        </p>
      )}

      {actionError !== null && (
        <p
          className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
          data-testid="returns-action-error"
        >
          {actionError}
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
            <p className="text-2xl font-semibold">{rupees(summary.total_taxable_minor)}</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-xs text-slate-500">Status</p>
            <p className="text-2xl font-semibold">{summary.status}</p>
          </div>
        </div>
      )}

      {/* 1. Generate (8.4 orchestration) */}
      <section
        className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
        data-testid="generate-section"
      >
        <h2 className="font-semibold">1. Generate returns</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Idempotent prepare→generate for GSTR-1 and GSTR-3B from the confirmed
          ledger. Safe to re-run.
        </p>
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={generating}
          className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          data-testid="generate-returns"
        >
          {generating ? "Generating…" : "Generate returns"}
        </button>

        {generateResult !== null && (
          <div
            className="mt-4 grid gap-3 sm:grid-cols-2"
            data-testid="generate-result"
          >
            {(["gstr1", "gstr3b"] as const).map((form) => {
              const entry = generateResult.returns[form];
              return (
                <div
                  key={form}
                  className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
                  data-testid={`generate-status-${form}`}
                >
                  <p className="text-sm font-semibold">
                    {form === "gstr1" ? "GSTR-1" : "GSTR-3B"} ·{" "}
                    <span
                      className={
                        entry.status === "READY"
                          ? "text-green-700 dark:text-green-300"
                          : "text-red-700 dark:text-red-300"
                      }
                    >
                      {entry.status}
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    Invoices: {entry.invoice_count}
                  </p>
                  {entry.status === "READY" && "txval_paise" in entry.totals && (
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      Taxable: {rupees(entry.totals.txval_paise)}
                    </p>
                  )}
                  {entry.status === "FAILED" && entry.error !== undefined && (
                    <p className="mt-1 text-xs text-red-700 dark:text-red-300">
                      {entry.error}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 2. Pre-filing validation checklist */}
      <section
        className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
        data-testid="validation-section"
      >
        <h2 className="font-semibold">2. Pre-filing validation</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          The error catcher: blocking findings must be fixed before filing;
          warnings are file-able but worth a look.
        </p>
        <ul className="mt-4 space-y-2" data-testid="validation-checklist">
          <li className="flex items-start gap-2 text-sm">
            <span
              className={blocked ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}
              data-testid="validation-blocking-state"
            >
              {blocked ? "✗" : "✓"}
            </span>
            <span>
              {blocked
                ? `${blocking.length} blocking issue${blocking.length === 1 ? "" : "s"}`
                : "No blocking issues — the period is file-ready"}
            </span>
          </li>
          {blocking.map((finding, i) => (
            <li
              key={`b-${finding.rule}-${i}`}
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              data-testid="validation-blocking-row"
            >
              <span className="font-mono text-xs">{finding.rule}</span>
              {" · "}
              {finding.message}
            </li>
          ))}
          {warnings.length === 0 ? (
            <li className="text-sm text-slate-500 dark:text-slate-400">
              No warnings.
            </li>
          ) : (
            warnings.map((finding, i) => (
              <li
                key={`w-${finding.rule}-${i}`}
                className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                data-testid="validation-warning-row"
              >
                <span className="font-mono text-xs">{finding.rule}</span>
                {" · "}
                {finding.message}
              </li>
            ))
          )}
        </ul>
      </section>

      {/* 3. HSN summary table */}
      <section
        className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
        data-testid="hsn-section"
      >
        <h2 className="font-semibold">3. HSN summary</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Outward line items aggregated by HSN/SAC × rate — must reconcile to
          GSTR-1.
        </p>
        {hsn === null || hsn.rows.length === 0 ? (
          <p
            className="mt-4 text-sm text-slate-500 dark:text-slate-400"
            data-testid="hsn-empty"
          >
            No outward line items for this period yet.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table
              className="w-full text-left text-[13px]"
              data-testid="hsn-table"
            >
              <thead>
                <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                  <th className="py-2 pr-4 font-medium">HSN/SAC</th>
                  <th className="py-2 pr-4 font-medium">Rate</th>
                  <th className="py-2 pr-4 font-medium">Lines</th>
                  <th className="py-2 pr-4 font-medium">Taxable</th>
                  <th className="py-2 pr-4 font-medium">IGST</th>
                  <th className="py-2 pr-4 font-medium">CGST</th>
                  <th className="py-2 pr-4 font-medium">SGST</th>
                  <th className="py-2 pr-4 font-medium">Cess</th>
                </tr>
              </thead>
              <tbody>
                {hsn.rows.map((row, i) => (
                  <tr
                    key={`${row.hsn_sac}-${row.rt}-${i}`}
                    className="border-b border-slate-100 dark:border-slate-800"
                    data-testid="hsn-row"
                  >
                    <td className="py-2 pr-4 font-mono">
                      {row.hsn_sac === "" ? "—" : row.hsn_sac}
                    </td>
                    <td className="py-2 pr-4">{row.rt}%</td>
                    <td className="py-2 pr-4">{row.num_of_lines}</td>
                    <td className="py-2 pr-4">{rupees(row.txval_paise)}</td>
                    <td className="py-2 pr-4">{rupees(row.iamt_paise)}</td>
                    <td className="py-2 pr-4">{rupees(row.camt_paise)}</td>
                    <td className="py-2 pr-4">{rupees(row.samt_paise)}</td>
                    <td className="py-2 pr-4">{rupees(row.csamt_paise)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr
                  className="font-semibold text-slate-700 dark:text-slate-200"
                  data-testid="hsn-totals"
                >
                  <td className="py-2 pr-4">Total</td>
                  <td className="py-2 pr-4" colSpan={2} />
                  <td className="py-2 pr-4">{rupees(hsn.totals.txval_paise)}</td>
                  <td className="py-2 pr-4">{rupees(hsn.totals.iamt_paise)}</td>
                  <td className="py-2 pr-4">{rupees(hsn.totals.camt_paise)}</td>
                  <td className="py-2 pr-4">{rupees(hsn.totals.samt_paise)}</td>
                  <td className="py-2 pr-4">{rupees(hsn.totals.csamt_paise)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      {/* 4. Format picker + downloads */}
      <section
        className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
        data-testid="download-section"
      >
        <h2 className="font-semibold">4. Download</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          JSON is the IRP offline-tool upload format; Excel (.xlsx) carries the
          same numbers, rendered server-side from the same payload.
        </p>

        <fieldset className="mt-4 flex items-center gap-4">
          <legend className="sr-only">Export format</legend>
          {(["json", "xlsx"] as const).map((value) => (
            <label key={value} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="export-format"
                value={value}
                checked={format === value}
                onChange={() => setFormat(value)}
                data-testid={`format-${value}`}
              />
              {value === "json" ? "JSON" : "Excel (.xlsx)"}
            </label>
          ))}
        </fieldset>

        {blocked && (
          <p
            className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
            data-testid="download-blocked"
          >
            Downloads are blocked until the {blocking.length} blocking issue
            {blocking.length === 1 ? "" : "s"} above are fixed.
          </p>
        )}

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
            <h3 className="font-semibold">GSTR-1</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Outward supply {format === "json" ? "JSON" : "Excel"} from
              confirmed ledger.
            </p>
            <button
              type="button"
              onClick={() => void handleDownload("gstr1")}
              disabled={
                (format === "json" && gstr1 === null) ||
                downloadingForm === "gstr1"
              }
              className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="download-gstr1"
            >
              {downloadingForm === "gstr1"
                ? "Downloading…"
                : `Download GSTR-1 ${format === "json" ? "JSON" : "Excel"}`}
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 p-6 dark:border-slate-800">
            <h3 className="font-semibold">GSTR-3B</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Summary return {format === "json" ? "JSON" : "Excel"} from
              confirmed ledger.
            </p>
            <button
              type="button"
              onClick={() => void handleDownload("gstr3b")}
              disabled={
                (format === "json" && gstr3b === null) ||
                downloadingForm === "gstr3b"
              }
              className="mt-4 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="download-gstr3b"
            >
              {downloadingForm === "gstr3b"
                ? "Downloading…"
                : `Download GSTR-3B ${format === "json" ? "JSON" : "Excel"}`}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
