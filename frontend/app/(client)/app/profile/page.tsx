"use client";

/**
 * Profile screen — PHASE8_PRODUCT_COMPLETENESS.md §3.8.6.
 * View + inline edit of full_name via GET/PATCH /me/profile (8.1); email is
 * read-only (the login credential, email-only auth). Phase 10.2: the header
 * lives in the shared (client)/app layout; after a rename this page pushes the
 * new name into the ShellContext so the shell user chip stays in sync.
 * FRONTEND_SPECIFICATION.md §4: API errors render inline, no silent catches;
 * react-hook-form/zod are not project deps yet, so validation is minimal
 * (non-empty, 255 chars) and the server remains the authority.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useShell } from "@/components/shared/ShellContext";
import {
  ApiError,
  fetchMe,
  fetchProfile,
  silentRefresh,
  updateProfile,
} from "@/lib/api/client";
import type { UserDto } from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

const MAX_NAME = 255;

export default function ProfilePage() {
  const router = useRouter();
  const shell = useShell();
  // Stable state setters (identity never changes) so the mount fetch below
  // cannot re-fire when the shell value object changes — that would loop.
  const setShellUserName = shell?.setUserName;
  const setShellGstAccounts = shell?.setGstAccounts;
  const [user, setUser] = useState<UserDto | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

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
        // /auth/me carries gst_accounts for the switcher; /me/profile is the
        // same user shape (8.1 contract) and stays the source of truth below.
        const profile = await fetchProfile();
        if (cancelled) return;
        setUser(profile);
        setNameDraft(profile.full_name);
        // 10.2: feed the shared shell header (user chip + GSTIN switcher).
        setShellUserName?.(profile.full_name);
        setShellGstAccounts?.(me.gst_accounts);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "failed to load profile");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, setShellUserName, setShellGstAccounts]);

  async function save() {
    const trimmed = nameDraft.trim();
    if (trimmed === "" || trimmed.length > MAX_NAME) {
      setSaveError("Name must be 1–255 characters.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSavedAt(null);
    try {
      const updated = await updateProfile(trimmed);
      setUser(updated);
      setNameDraft(updated.full_name);
      // 10.2: keep the shell user chip in sync after the rename.
      setShellUserName?.(updated.full_name);
      setSavedAt(new Date().toISOString());
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  if (user === null && loadError === null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center text-sm text-slate-500">
        Checking session…
      </div>
    );
  }

  if (loadError !== null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
        <p className="text-sm text-red-600 dark:text-red-400" data-testid="profile-load-error">
          {loadError}
        </p>
      </div>
    );
  }

  const dirty = user !== null && nameDraft !== user.full_name;
  const disableSave = saving || !dirty || nameDraft.trim() === "" || nameDraft.trim().length > MAX_NAME;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
      <h1 className="text-2xl font-semibold">Profile</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Your account details. Your email is your login and cannot be changed.
      </p>

      <div className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800">
        <div className="space-y-6">
          <div>
            <label htmlFor="profile-email" className="block text-sm font-medium">
              Email
            </label>
            <input
              id="profile-email"
              type="email"
              value={user?.email ?? ""}
              readOnly
              disabled
              aria-readonly="true"
              data-testid="profile-email"
              className="mt-1 w-full cursor-not-allowed rounded-md border border-slate-200 bg-slate-100 px-3 py-2 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
            />
            <p className="mt-1 text-xs text-slate-400">
              Read-only — your email is your login (email-only auth).
            </p>
          </div>

          <div>
            <label htmlFor="profile-name" className="block text-sm font-medium">
              Full name
            </label>
            <input
              id="profile-name"
              type="text"
              value={nameDraft}
              maxLength={MAX_NAME}
              onChange={(e) => {
                setNameDraft(e.target.value);
                setSaveError(null);
                setSavedAt(null);
              }}
              data-testid="profile-name-input"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={disableSave}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="profile-save"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                if (user !== null) setNameDraft(user.full_name);
                setSaveError(null);
                setSavedAt(null);
              }}
              disabled={!dirty || saving}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
              data-testid="profile-cancel"
            >
              Cancel
            </button>
            {savedAt !== null && (
              <span
                className="text-sm font-medium text-green-700 dark:text-green-300"
                data-testid="profile-saved"
              >
                Saved ✓
              </span>
            )}
          </div>

          {saveError !== null && (
            <p
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              role="alert"
              data-testid="profile-error"
            >
              {saveError}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}