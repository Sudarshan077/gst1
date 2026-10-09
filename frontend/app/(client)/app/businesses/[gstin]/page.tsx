"use client";

/**
 * Business detail + edit — PHASE8_PRODUCT_COMPLETENESS.md §3.8.8.
 * /app/businesses/[gstin]: GET /gst-accounts/{gstin}/overview (8.3 — detail +
 * this-FY period statuses) with inline edit of legal_name, trade_name,
 * registered_address, filing_scheme via PATCH /gst-accounts/{gstin} (8.3;
 * requires FILER/ADMIN server-side — the UI shows the fields read-only for
 * VIEWER). GSTIN, PAN, state are registration identities: never editable.
 * Phase 10.2: the header lives in the shared (client)/app layout; this page
 * pushes the user name + GST accounts into the ShellContext.
 * FRONTEND_SPECIFICATION.md §4: API errors render inline, no silent catches.
 */
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useShell } from "@/components/shared/ShellContext";
import {
  ApiError,
  fetchMe,
  getGstAccountOverview,
  silentRefresh,
  updateGstAccount,
} from "@/lib/api/client";
import type { GstAccountOverviewDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

const MAX_NAME = 255;
const MAX_ADDRESS = 1000;
const FILING_SCHEMES = ["REGULAR_MONTHLY", "QRMP", "COMPOSITION"] as const;

/** Status chip color per FRONTEND_SPECIFICATION.md §2 status palette. */
function statusClass(status: string): string {
  if (status === "FILED") return "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300";
  if (status === "LOCKED") return "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300";
  if (status === "READY") return "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300";
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"; // OPEN / DRAFT / etc.
}

function fmtDate(iso: string | null): string {
  return iso === null ? "—" : iso.slice(0, 10);
}

export default function BusinessDetailPage() {
  const router = useRouter();
  const shell = useShell();
  // Stable state setters (identity never changes) so the mount fetch below
  // cannot re-fire when the shell value object changes — that would loop.
  const setShellUserName = shell?.setUserName;
  const setShellGstAccounts = shell?.setGstAccounts;
  const params = useParams<{ gstin: string }>();
  const gstin = params.gstin;
  const [overview, setOverview] = useState<GstAccountOverviewDto | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [tradeDraft, setTradeDraft] = useState("");
  const [addressDraft, setAddressDraft] = useState("");
  const [schemeDraft, setSchemeDraft] = useState("");

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
        // 10.2: feed the shared shell header (user chip + GSTIN switcher).
        setShellUserName?.(me.user.full_name);
        setShellGstAccounts?.(me.gst_accounts);
        const data = await getGstAccountOverview(gstin);
        if (cancelled) return;
        setOverview(data);
        setNameDraft(data.detail.legal_name);
        setTradeDraft(data.detail.trade_name ?? "");
        setAddressDraft(data.detail.registered_address ?? "");
        setSchemeDraft(data.detail.filing_scheme);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "failed to load business");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [gstin, router, setShellUserName, setShellGstAccounts]);

  const detail = overview?.detail ?? null;
  const canEdit = detail !== null && detail.role !== "VIEWER";

  async function save() {
    const name = nameDraft.trim();
    if (name === "" || name.length > MAX_NAME) {
      setSaveError("Legal name must be 1–255 characters.");
      return;
    }
    if (addressDraft.length > MAX_ADDRESS) {
      setSaveError(`Registered address must be at most ${MAX_ADDRESS} characters.`);
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSavedAt(null);
    try {
      const updated = await updateGstAccount(gstin, {
        legal_name: name,
        trade_name: tradeDraft.trim() === "" ? undefined : tradeDraft.trim(),
        registered_address: addressDraft.trim() === "" ? undefined : addressDraft.trim(),
        filing_scheme: schemeDraft,
      });
      setOverview(
        (prev) =>
          prev === null ? prev : { ...prev, detail: { ...prev.detail, ...updated } },
      );
      setNameDraft(updated.legal_name);
      setTradeDraft(updated.trade_name ?? "");
      setAddressDraft(updated.registered_address ?? "");
      setSchemeDraft(updated.filing_scheme);
      setSavedAt(new Date().toISOString());
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "failed to save business");
    } finally {
      setSaving(false);
    }
  }

  if (overview === null && loadError === null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center text-sm text-slate-500">
        Checking session…
      </div>
    );
  }

  if (loadError !== null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
        <p className="text-sm text-red-600 dark:text-red-400" data-testid="business-load-error">
          {loadError}
        </p>
      </div>
    );
  }

  const dirty =
    detail !== null &&
    (nameDraft !== detail.legal_name ||
      tradeDraft !== (detail.trade_name ?? "") ||
      addressDraft !== (detail.registered_address ?? "") ||
      schemeDraft !== detail.filing_scheme);
  const disableSave = saving || !dirty || !canEdit;

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8">
      <Link
        href="/app/businesses"
        className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        data-testid="business-back-link"
      >
          ← All businesses
        </Link>
        <h1 className="mt-2 text-2xl font-semibold" data-testid="business-detail-title">
          {detail?.legal_name ?? ""}
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400" data-testid="business-detail-gstin">
          {gstin} · {detail?.state_code} · {detail?.filing_scheme} · role {detail?.role}
        </p>

        <div className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Registration details</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <span className="block text-xs font-medium">GSTIN</span>
              <span className="text-sm" data-testid="business-field-gstin">{gstin}</span>
            </div>
            <div>
              <span className="block text-xs font-medium">PAN</span>
              <span className="text-sm" data-testid="business-field-pan">{detail?.pan}</span>
            </div>
            <div>
              <span className="block text-xs font-medium">State code</span>
              <span className="text-sm">{detail?.state_code}</span>
            </div>
            <div>
              <span className="block text-xs font-medium">IRN applicable</span>
              <span className="text-sm">{detail?.irn_applicable ? "Yes" : "No"}</span>
            </div>
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <label htmlFor="business-legal-name" className="block text-sm font-medium">
                Legal name
              </label>
              <input
                id="business-legal-name"
                type="text"
                maxLength={MAX_NAME}
                value={nameDraft}
                disabled={!canEdit}
                onChange={(e) => {
                  setNameDraft(e.target.value);
                  setSaveError(null);
                  setSavedAt(null);
                }}
                data-testid="business-legal-name"
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <div>
              <label htmlFor="business-trade-name" className="block text-sm font-medium">
                Trade name
              </label>
              <input
                id="business-trade-name"
                type="text"
                maxLength={MAX_NAME}
                value={tradeDraft}
                disabled={!canEdit}
                onChange={(e) => {
                  setTradeDraft(e.target.value);
                  setSaveError(null);
                  setSavedAt(null);
                }}
                data-testid="business-trade-name"
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <div>
              <label htmlFor="business-address" className="block text-sm font-medium">
                Registered address
              </label>
              <textarea
                id="business-address"
                maxLength={MAX_ADDRESS}
                rows={2}
                value={addressDraft}
                disabled={!canEdit}
                onChange={(e) => {
                  setAddressDraft(e.target.value);
                  setSaveError(null);
                  setSavedAt(null);
                }}
                data-testid="business-address"
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <div>
              <label htmlFor="business-scheme" className="block text-sm font-medium">
                Filing scheme
              </label>
              <select
                id="business-scheme"
                value={schemeDraft}
                disabled={!canEdit}
                onChange={(e) => {
                  setSchemeDraft(e.target.value);
                  setSaveError(null);
                  setSavedAt(null);
                }}
                data-testid="business-scheme"
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:disabled:bg-slate-800"
              >
                {FILING_SCHEMES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            {canEdit ? (
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={save}
                  disabled={disableSave}
                  className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                  data-testid="business-save"
                >
                  {saving ? "Saving…" : "Save changes"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (detail === null) return;
                    setNameDraft(detail.legal_name);
                    setTradeDraft(detail.trade_name ?? "");
                    setAddressDraft(detail.registered_address ?? "");
                    setSchemeDraft(detail.filing_scheme);
                    setSaveError(null);
                    setSavedAt(null);
                  }}
                  disabled={!dirty || saving}
                  className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  data-testid="business-cancel"
                >
                  Cancel
                </button>
                {savedAt !== null && (
                  <span
                    className="text-sm font-medium text-green-700 dark:text-green-300"
                    data-testid="business-saved"
                  >
                    Saved ✓
                  </span>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400" data-testid="business-readonly-note">
                You are a VIEWER on this business — only FILER and ADMIN can edit.
              </p>
            )}

            {saveError !== null && (
              <p
                className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
                role="alert"
                data-testid="business-save-error"
              >
                {saveError}
              </p>
            )}
          </div>
        </div>

        <div className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800">
          <h2 className="text-sm font-semibold">
            Filing status — FY {overview?.fy}
          </h2>
          <div className="mt-3 flex flex-wrap gap-2" data-testid="business-fy-status">
            {overview?.periods.map((p) => (
              <span
                key={p.fp}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(p.status)}`}
                data-testid="business-period-chip"
                title={p.gstr1_due_date !== null ? `GSTR-1 due ${fmtDate(p.gstr1_due_date)}` : undefined}
              >
                {p.fp} · {p.status}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Periods show the server-computed status (OPEN when no filings exist yet);
            GSTR-1 due dates appear once a period exists.
          </p>
        </div>
    </main>
  );
}