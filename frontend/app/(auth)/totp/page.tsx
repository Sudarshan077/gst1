"use client";

/**
 * TOTP self-enrollment — QR + verify (SECURITY §1: TOTP is a per-user 2FA
 * option; verify client-side before enabling). With the unified v4 model
 * there is no role split, so after enabling the user returns to /app.
 */
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

import { ApiError, totpSetup, totpVerify } from "@/lib/api/client";
import { setSessionCookie } from "@/lib/auth/session";

type Stage = "setup" | "verify" | "enabled";

export default function TotpPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("setup");
  const [secret, setSecret] = useState("");
  const [qrUri, setQrUri] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const qrCanvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (stage === "verify" && qrCanvasRef.current !== null && qrUri !== "") {
      QRCode.toCanvas(qrCanvasRef.current, qrUri, { width: 220 }).catch(() => {
        // QR render failure keeps the secret fallback visible below.
      });
    }
  }, [stage, qrUri]);

  async function begin(e: React.MouseEvent<HTMLButtonElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await totpSetup();
      setSecret(res.secret);
      setQrUri(res.qr_uri);
      setStage("verify");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "TOTP setup failed");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await totpVerify(code);
      setSessionCookie();
      setStage("enabled");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "invalid TOTP code");
    } finally {
      setBusy(false);
    }
  }

  function goToShell() {
    router.push("/app");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-md flex-col justify-center px-4">
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-semibold">Two-factor authentication</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Optional second factor — scan with any authenticator app.
        </p>

        {stage === "setup" && (
          <button
            type="button"
            onClick={begin}
            disabled={busy}
            className="mt-6 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            data-testid="totp-begin"
          >
            {busy ? "Generating…" : "Generate QR code"}
          </button>
        )}

        {stage === "verify" && (
          <form onSubmit={verify} className="mt-6 space-y-4">
            <div className="flex justify-center">
              <canvas ref={qrCanvasRef} data-testid="totp-qr" />
            </div>
            <p
              className="break-all rounded-md bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
              data-testid="totp-secret"
            >
              {secret}
            </p>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-lg tracking-widest dark:border-slate-700 dark:bg-slate-800"
              placeholder="6-digit code"
              data-testid="totp-code"
            />
            <button
              type="submit"
              disabled={busy || code.length !== 6}
              className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="totp-verify-btn"
            >
              {busy ? "Verifying…" : "Verify & enable"}
            </button>
          </form>
        )}

        {stage === "enabled" && (
          <div className="mt-6 space-y-4">
            <p
              className="text-sm font-medium text-green-700 dark:text-green-400"
              data-testid="totp-enabled-banner"
            >
              ✓ TOTP enabled
            </p>
            <button
              type="button"
              onClick={goToShell}
              className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="totp-continue"
            >
              Continue →
            </button>
          </div>
        )}

        {error !== null && (
          <p
            className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
            role="alert"
            data-testid="totp-error"
          >
            {error}
          </p>
        )}
      </div>
    </main>
  );
}