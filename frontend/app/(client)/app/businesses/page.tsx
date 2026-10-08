"use client";

/**
 * Manage businesses — PHASE8_PRODUCT_COMPLETENESS.md §3.8.8.
 * List + add GSTIN. The add form validates the checksum client-side too
 * with the same mod-36 rule (lib/validation/gstin.ts mirror; server always
 * re-validates). Renders ShellNav so it is reachable by clicking the nav
 * (8.5 gate). FRONTEND_SPECIFICATION.md §4: API errors render inline, no
 * silent catches; empty state has a designed next action.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ShellNav } from "@/components/shared/ShellNav";
import {
  ApiError,
  addGstAccount,
  fetchMe,
  listGstAccounts,
  setAccessToken,
  silentRefresh,
} from "@/lib/api/client";
import type { GstAccountDto, GstinRefDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";
import { gstinChecksumValid } from "@/lib/validation/gstin";

const MAX_NAME = 255;

export default function BusinessesPage() {
  const router = useRouter();
  const [userName, setUserName] = useState("…");
  const [accounts, setAccounts] = useState<GstAccountDto[] | null>(null);
  const [gstAccounts, setGstAccounts] = useState<GstinRefDto[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [gstinDraft, setGstinDraft] = useState("");
  const [nameDraft, setNameDraft] = useState("");

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
        setUserName(me.user.full_name);
        setGstAccounts(me.gst_accounts);
        const list = await listGstAccounts();
        if (cancelled) return;
        setAccounts(list);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "failed to load businesses");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function addBusiness() {
    const gstin = gstinDraft.trim().toUpperCase();
    const name = nameDraft.trim();
    if (name === "" || name.length > MAX_NAME) {
      setAddError("Legal name must be 1–255 characters.");
      return;
    }
    if (gstin.length !== 15 || !gstinChecksumValid(gstin)) {
      setAddError("Invalid GSTIN — format or checksum fails the mod-36 rule.");
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      const created = await addGstAccount({ gstin, legal_name: name });
      setAccounts((prev) => [...(prev ?? []), created]);
      setGstAccounts((prev) => [
        ...prev,
        { gstin: created.gstin, role: created.role, legal_name: created.legal_name },
      ]);
      setGstinDraft("");
      setNameDraft("");
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : "failed to add business");
    } finally {
      setAdding(false);
    }
  }

  async function signOut() {
    setAccessToken(null);
    clearSession();
    router.push("/login");
  }

  if (accounts === null && loadError === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Checking session…
      </div>
    );
  }

  if (loadError !== null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
        <p className="text-sm text-red-600 dark:text-red-400" data-testid="businesses-load-error">
          {loadError}
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <ShellNav
        roleLabel="GST Filing"
        userName={userName}
        onSignOut={signOut}
        gstAccounts={gstAccounts}
      />
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8">
        <h1 className="text-2xl font-semibold">Businesses</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          GSTINs linked to your account — open one to view and edit its registration details.
        </p>

        <div className="mt-6 rounded-xl border border-slate-200 p-5 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Add a business</h2>
          <div className="mt-3 flex flex-wrap gap-3">
            <div>
              <label htmlFor="business-add-gstin" className="block text-xs font-medium">
                GSTIN
              </label>
              <input
                id="business-add-gstin"
                type="text"
                inputMode="numeric"
                placeholder="15-character GSTIN"
                maxLength={15}
                value={gstinDraft}
                onChange={(e) => {
                  setGstinDraft(e.target.value);
                  setAddError(null);
                }}
                data-testid="business-add-gstin"
                className="mt-1 w-56 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm uppercase dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <div className="flex-1 min-w-56">
              <label htmlFor="business-add-name" className="block text-xs font-medium">
                Legal name
              </label>
              <input
                id="business-add-name"
                type="text"
                placeholder="Registered legal name"
                maxLength={MAX_NAME}
                value={nameDraft}
                onChange={(e) => {
                  setNameDraft(e.target.value);
                  setAddError(null);
                }}
                data-testid="business-add-name"
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
            </div>
            <button
              type="button"
              onClick={addBusiness}
              disabled={adding || nameDraft.trim() === "" || gstinDraft.trim().length !== 15}
              className="mt-5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="business-add-submit"
            >
              {adding ? "Adding…" : "Add business"}
            </button>
          </div>
          {addError !== null && (
            <p
              className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              role="alert"
              data-testid="business-add-error"
            >
              {addError}
            </p>
          )}
        </div>

        <div className="mt-8 grid gap-4" data-testid="business-list">
          {accounts !== null && accounts.length > 0 ? (
            accounts.map((acc) => (
              <div
                key={acc.gstin}
                className="flex items-center justify-between rounded-lg border border-slate-200 p-4 dark:border-slate-800"
                data-testid="business-card"
              >
                <div>
                  <div className="font-semibold" data-testid="business-card-name">
                    {acc.legal_name}
                  </div>
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    {acc.gstin} · {acc.state_code} · {acc.filing_scheme}
                  </div>
                </div>
                <Link
                  href={`/app/businesses/${acc.gstin}`}
                  className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
                  data-testid="business-open-link"
                >
                  Open
                </Link>
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No businesses yet — add a GSTIN above to begin.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}