"use client";

/**
 * Settings screen — PHASE8_PRODUCT_COMPLETENESS.md §3.8.7.
 * Notification preferences (email / in-app) persisted via PATCH /me/settings
 * (which delegates to the /me/notification-prefs handler — 8.2 contract, no
 * duplicated write logic), TOTP status with an enable/disable entry that
 * links through to /totp, sign-out-everywhere via POST /auth/logout-all, and
 * an account summary from GET /me/settings' session block. Phase 10.2: the
 * header lives in the shared (client)/app layout; this page pushes the user
 * name + GST accounts into the ShellContext to keep the nav in sync.
 * FRONTEND_SPECIFICATION.md §4: API errors render inline, no silent catches.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useShell } from "@/components/shared/ShellContext";
import {
  ApiError,
  dpdpExport,
  dpdpRequestErasure,
  fetchMe,
  fetchSettings,
  requestOtp,
  silentRefresh,
  signOutEverywhere,
  updateSettings,
} from "@/lib/api/client";
import type {
  NotificationPrefs,
  SettingsDto,
  UserDto,
} from "@/lib/api/client";
import { clearSession } from "@/lib/auth/session";

/** Channel rows shown in the prefs card. In-app is always created (services/
 * notifications.py); email defaults on server-side. */
const PREF_CHANNELS = [
  {
    key: "email" as const,
    label: "Email",
    description: "Deadline and status notifications to your email",
  },
  {
    key: "in_app" as const,
    label: "In-app",
    description: "Notifications in the app notification list",
  },
];

/** Read the two known booleans out of the free-form prefs column. */
function prefsFromSettings(settings: SettingsDto): NotificationPrefs {
  const raw = settings.notification_preferences ?? {};
  return {
    email: raw.email !== undefined ? raw.email === true : true,
    in_app: raw.in_app !== undefined ? raw.in_app === true : true,
  };
}

export default function SettingsPage() {
  const router = useRouter();
  const shell = useShell();
  // Stable state setters (identity never changes) so the mount fetch below
  // cannot re-fire when the shell value object changes — that would loop.
  const setShellUserName = shell?.setUserName;
  const setShellGstAccounts = shell?.setGstAccounts;
  const [user, setUser] = useState<UserDto | null>(null);
  const [settings, setSettings] = useState<SettingsDto | null>(null);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [savedPrefs, setSavedPrefs] = useState<NotificationPrefs | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [revokedInfo, setRevokedInfo] = useState<string | null>(null);
  const [dpdpAction, setDpdpAction] = useState<"export" | "erasure" | null>(null);
  const [dpdpConfirmErase, setDpdpConfirmErase] = useState(false);
  const [dpdpOtp, setDpdpOtp] = useState("");
  const [dpdpDevOtp, setDpdpDevOtp] = useState<string | null>(null);
  const [dpdpError, setDpdpError] = useState<string | null>(null);
  const [dpdpBusy, setDpdpBusy] = useState(false);
  const [dpdpStatus, setDpdpStatus] = useState<string | null>(null);

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
        const loaded = await fetchSettings();
        if (cancelled) return;
        setUser(me.user);
        // 10.2: feed the shared shell header (user chip + GSTIN switcher).
        setShellUserName?.(me.user.full_name);
        setShellGstAccounts?.(me.gst_accounts);
        setSettings(loaded);
        const parsed = prefsFromSettings(loaded);
        setPrefs(parsed);
        setSavedPrefs(parsed);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "failed to load settings");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, setShellUserName, setShellGstAccounts]);

  async function togglePref(key: keyof NotificationPrefs) {
    if (prefs === null) return;
    setPrefs({ ...prefs, [key]: !prefs[key] });
    setSaveError(null);
    setSavedAt(null);
  }

  async function save() {
    if (prefs === null) return;
    setSaving(true);
    setSaveError(null);
    setSavedAt(null);
    try {
      const updated = await updateSettings(prefs);
      const parsed = prefsFromSettings(updated);
      setSettings(updated);
      setPrefs(parsed);
      setSavedPrefs(parsed);
      setSavedAt(new Date().toISOString());
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  async function revokeSessions() {
    setSessionError(null);
    try {
      const result = await signOutEverywhere();
      // Every refresh family is dead; this browser keeps its short-lived
      // access JWT, so re-read the aggregate for the zeroed count.
      const refreshed = await fetchSettings();
      setSettings(refreshed);
      setRevokedInfo(
        result.revoked_sessions === 1
          ? "Signed out 1 device. This browser stays signed in."
          : `Signed out ${result.revoked_sessions} devices. This browser stays signed in.`,
      );
    } catch (err) {
      setSessionError(err instanceof ApiError ? err.message : "failed to revoke sessions");
    }
  }

  async function startDpdp(action: "export" | "erasure") {
    setDpdpConfirmErase(false);
    setDpdpError(null);
    setDpdpStatus(null);
    setDpdpOtp("");
    setDpdpDevOtp(null);
    if (!user) {
      setDpdpError("Your account details are still loading — try again.");
      return;
    }
    setDpdpBusy(true);
    try {
      // Step-up proof (SECURITY §1): issue a fresh OTP for the authenticated
      // email, then re-send it back via the X-OTP header on the DPDP call.
      const res = await requestOtp(user.email, "LOGIN");
      setDpdpDevOtp(res.dev_otp);
      setDpdpAction(action);
    } catch (err) {
      setDpdpError(err instanceof ApiError ? err.message : "failed to send step-up code");
    } finally {
      setDpdpBusy(false);
    }
  }

  async function confirmDpdp(e: React.FormEvent) {
    e.preventDefault();
    if (dpdpOtp.length !== 6) {
      setDpdpError("Enter the 6-digit code.");
      return;
    }
    setDpdpBusy(true);
    setDpdpError(null);
    try {
      if (dpdpAction === "export") {
        const res = await dpdpExport(dpdpOtp);
        const blob = new Blob([JSON.stringify(res.export, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "dpdp-export.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setDpdpStatus(
          `Export complete (request ${res.request_id}) — download started.`,
        );
      } else {
        const res = await dpdpRequestErasure(dpdpOtp);
        setDpdpStatus(
          `Erasure requested (${res.request_id}) — SLA due ${res.sla_due_date}. Statutory 8-FY retention still applies.`,
        );
      }
      setDpdpAction(null);
      setDpdpOtp("");
      setDpdpDevOtp(null);
    } catch (err) {
      setDpdpError(err instanceof ApiError ? err.message : "DPDP action failed");
    } finally {
      setDpdpBusy(false);
    }
  }

  function cancelDpdp() {
    setDpdpAction(null);
    setDpdpConfirmErase(false);
    setDpdpOtp("");
    setDpdpDevOtp(null);
    setDpdpError(null);
  }

  if (settings === null && loadError === null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center text-sm text-slate-500">
        Checking session…
      </div>
    );
  }

  if (loadError !== null) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
        <p
          className="text-sm text-red-600 dark:text-red-400"
          data-testid="settings-load-error"
        >
          {loadError}
        </p>
      </div>
    );
  }

  const dirty = prefs !== null && savedPrefs !== null && prefs !== savedPrefs;
  const activeSessions = settings?.session.active_sessions ?? 0;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
      <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Notification preferences, security, and session management for your account.
        </p>

        {/* Account summary (8.7 deliverable) */}
        <section
          className="mt-8 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
          data-testid="settings-account-summary"
        >
          <h2 className="text-base font-semibold">Account</h2>
          <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-500 dark:text-slate-400">Email</dt>
              <dd className="font-medium" data-testid="settings-summary-email">
                {user?.email ?? "…"}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500 dark:text-slate-400">Businesses</dt>
              <dd className="font-medium" data-testid="settings-summary-businesses">
                {shell?.gstAccounts.length ?? 0}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500 dark:text-slate-400">Active sessions</dt>
              <dd className="font-medium" data-testid="settings-active-sessions">
                {activeSessions}
              </dd>
            </div>
          </dl>
        </section>

        {/* Notification preferences (done_when gate: toggle -> save -> persists) */}
        <section
          className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
          data-testid="settings-notifications"
        >
          <h2 className="text-base font-semibold">Notifications</h2>
          <div className="mt-3 space-y-3">
            {PREF_CHANNELS.map((channel) => (
              <label
                key={channel.key}
                className="flex cursor-pointer items-start justify-between gap-4"
              >
                <span>
                  <span className="block text-sm font-medium">{channel.label}</span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">
                    {channel.description}
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={prefs?.[channel.key] ?? false}
                  onChange={() => {
                    void togglePref(channel.key);
                  }}
                  data-testid={`settings-pref-${channel.key}`}
                  className="mt-1 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800"
                />
              </label>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                void save();
              }}
              disabled={saving || !dirty}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="settings-save"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                if (savedPrefs !== null) setPrefs(savedPrefs);
                setSaveError(null);
                setSavedAt(null);
              }}
              disabled={!dirty || saving}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
              data-testid="settings-cancel"
            >
              Cancel
            </button>
            {savedAt !== null && (
              <span
                className="text-sm font-medium text-green-700 dark:text-green-300"
                data-testid="settings-saved"
              >
                Saved ✓
              </span>
            )}
          </div>
          {saveError !== null && (
            <p
              className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              role="alert"
              data-testid="settings-error"
            >
              {saveError}
            </p>
          )}
        </section>

        {/* Security / TOTP (done_when: TOTP entry links through) */}
        <section
          className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
          data-testid="settings-security"
        >
          <h2 className="text-base font-semibold">Security</h2>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Two-factor authentication (TOTP)</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {settings?.totp_enabled
                  ? "Enabled — your authenticator app is required as a second factor."
                  : "Add a second factor with any authenticator app."}
              </p>
            </div>
            <span
              className={
                settings?.totp_enabled
                  ? "rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700 dark:bg-green-950 dark:text-green-300"
                  : "rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              }
              data-testid="settings-totp-status"
            >
              {settings?.totp_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <div className="mt-4">
            <Link
              href="/totp"
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
              data-testid="settings-totp-link"
            >
              {settings?.totp_enabled ? "Manage 2FA →" : "Enable 2FA →"}
            </Link>
          </div>
        </section>

        {/* Session management (sign-out-everywhere, 8.7 deliverable) */}
        <section
          className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
          data-testid="settings-session"
        >
          <h2 className="text-base font-semibold">Session</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {activeSessions} active {activeSessions === 1 ? "device" : "devices"} ·
            sessions stay signed in for up to {settings?.session.refresh_ttl_days ?? 7} days
          </p>
          <button
            type="button"
            onClick={() => {
              void revokeSessions();
            }}
            className="mt-4 rounded-md border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
            data-testid="settings-signout-everywhere"
          >
            Sign out everywhere
          </button>
          {revokedInfo !== null && (
            <p
              className="mt-3 text-sm font-medium text-green-700 dark:text-green-300"
              data-testid="settings-revoked-info"
            >
              {revokedInfo}
            </p>
          )}
          {sessionError !== null && (
            <p
              className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              role="alert"
              data-testid="settings-session-error"
            >
              {sessionError}
            </p>
          )}
        </section>

        {/* Data Privacy (DPDP) — self-service export + erasure (step-up protected) */}
        <section
          className="mt-6 rounded-xl border border-slate-200 p-6 dark:border-slate-800"
          data-testid="settings-dpdp"
        >
          <h2 className="text-base font-semibold">Data Privacy (DPDP)</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Download a machine-readable copy of your data or request erasure.
            Sensitive actions require re-entering a one-time code.
          </p>

          {dpdpAction === null && !dpdpConfirmErase && (
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void startDpdp("export")}
                disabled={dpdpBusy}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                data-testid="dpdp-export-btn"
              >
                Export My Data
              </button>
              <button
                type="button"
                onClick={() => setDpdpConfirmErase(true)}
                disabled={dpdpBusy}
                className="rounded-md border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
                data-testid="dpdp-erase-btn"
              >
                Request Data Erasure
              </button>
            </div>
          )}

          {dpdpConfirmErase && dpdpAction === null && (
            <div
              className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950"
              data-testid="dpdp-erase-confirm"
            >
              <p className="text-sm text-amber-800 dark:text-amber-200">
                Request erasure of your data? This queues a 30-day SLA request;
                statutory 8-financial-year retention still applies.
              </p>
              <div className="mt-3 flex gap-3">
                <button
                  type="button"
                  onClick={() => void startDpdp("erasure")}
                  disabled={dpdpBusy}
                  className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                  data-testid="dpdp-erase-confirm-btn"
                >
                  Yes, request erasure
                </button>
                <button
                  type="button"
                  onClick={() => setDpdpConfirmErase(false)}
                  className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {dpdpAction !== null && (
            <form onSubmit={confirmDpdp} className="mt-4 space-y-3" noValidate>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {dpdpAction === "export"
                  ? "Enter the code sent to your email to confirm export."
                  : "Enter the code sent to your email to confirm erasure."}
              </p>
              {dpdpDevOtp !== null && (
                <p
                  className="rounded-md bg-amber-50 px-3 py-2 font-mono text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                  data-testid="dpdp-dev-otp"
                >
                  dev code: {dpdpDevOtp}
                </p>
              )}
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={dpdpOtp}
                onChange={(e) => setDpdpOtp(e.target.value.replace(/\D/g, ""))}
                className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-lg tracking-widest dark:border-slate-700 dark:bg-slate-800"
                placeholder="6-digit code"
                data-testid="dpdp-otp"
              />
              <div className="flex gap-3">
                <button
                  type="submit"
                  disabled={dpdpBusy || dpdpOtp.length !== 6}
                  className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                  data-testid="dpdp-confirm"
                >
                  {dpdpBusy ? "Confirming…" : "Confirm"}
                </button>
                <button
                  type="button"
                  onClick={cancelDpdp}
                  disabled={dpdpBusy}
                  className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {dpdpError !== null && (
            <p
              className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
              role="alert"
              data-testid="dpdp-error"
            >
              {dpdpError}
            </p>
          )}
          {dpdpStatus !== null && (
            <p
              className="mt-3 rounded-md bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-950 dark:text-green-300"
              data-testid="dpdp-status"
            >
              {dpdpStatus}
            </p>
          )}
        </section>
      </main>
  );
}