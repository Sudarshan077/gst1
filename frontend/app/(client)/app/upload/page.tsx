"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { fetchMe, silentRefresh } from "@/lib/api/client";

export default function UploadFallbackPage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function redirect() {
      try {
        await silentRefresh();
        const me = await fetchMe();
        const gstin = me.gst_accounts[0]?.gstin;
        if (!cancelled && gstin) {
          router.replace(`/app/upload/${gstin}/092026`);
          return;
        }
      } catch {
        // session missing or failed
      }
      if (!cancelled) {
        router.replace("/app");
      }
    }
    void redirect();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-12">
      <div className="flex flex-col items-center justify-center space-y-4 text-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Redirecting to your active upload workspace…
        </p>
      </div>
    </main>
  );
}
