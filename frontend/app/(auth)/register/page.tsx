"use client";

/**
 * Registration — one user type (no role pick), OTP with REGISTER purpose.
 * New users are auto-created by the backend on REGISTER verify; GSTIN
 * attachment (not a role choice) determines what the user can operate on.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  requestOtp,
  setAccessToken,
  verifyOtp,
} from "@/lib/api/client";
import { setSessionCookie } from "@/lib/auth/session";

type Stage = "identifier" | "otp";

export default function RegisterPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [otp, setOtp] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("identifier");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function request(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await requestOtp(identifier, "REGISTER");
      setDevOtp(res.dev_otp);
      setStage("otp");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "failed to send OTP");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await verifyOtp(identifier, otp);
      setAccessToken(res.access_token);
      // One user type — session cookie is routing only (FRONTEND_SPEC §4).
      setSessionCookie();
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "OTP verification failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (done) {
      router.push("/app");
      router.refresh();
    }
  }, [done, router]);

  return (
    <main className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-md flex-col justify-center px-4">
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-semibold">Create your account</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Email address — we send a 6-digit code.
        </p>

        {stage === "identifier" && (
          <form onSubmit={request} className="mt-6 space-y-4">
            <label className="block text-sm font-medium">
              Email
              <input
                type="email"
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
                placeholder="you@firm.com"
                data-testid="reg-identifier"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="reg-request-otp"
            >
              {busy ? "Sending…" : "Send code"}
            </button>
          </form>
        )}

        {stage === "otp" && (
          <form onSubmit={verify} className="mt-6 space-y-4">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Code sent to <span className="font-mono">{identifier}</span>
            </p>
            {devOtp !== null && (
              <p
                className="rounded-md bg-amber-50 px-3 py-2 font-mono text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                data-testid="reg-dev-otp"
              >
                dev code: {devOtp}
              </p>
            )}
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-lg tracking-widest dark:border-slate-700 dark:bg-slate-800"
              placeholder="6-digit code"
              data-testid="reg-otp"
            />
            <button
              type="submit"
              disabled={busy || otp.length !== 6}
              className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="reg-verify"
            >
              {busy ? "Verifying…" : "Verify & continue"}
            </button>
            <button
              type="button"
              onClick={() => setStage("identifier")}
              className="text-sm text-slate-500 hover:underline"
            >
              ← change identifier
            </button>
          </form>
        )}

        {error !== null && (
          <p
            className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
            role="alert"
            data-testid="reg-error"
          >
            {error}
          </p>
        )}

        <p className="mt-6 text-sm text-slate-500 dark:text-slate-400">
          Already registered?{" "}
          <a href="/login" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Sign in
          </a>
        </p>
      </div>
    </main>
  );
}