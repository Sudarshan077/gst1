"use client";

/**
 * File / review queue page for a GSTIN + period. Lists uploaded documents with
 * extraction status and lets the user open the review-confirm screen.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, DocumentRow, listDocuments } from "@/lib/api/client";

function statusColor(status: string) {
  switch (status) {
    case "CONFIRMED":
      return "text-green-700 dark:text-green-300";
    case "NEEDS_REVIEW":
      return "text-amber-700 dark:text-amber-300";
    case "FAILED":
      return "text-red-700 dark:text-red-300";
    default:
      return "text-slate-500 dark:text-slate-400";
  }
}

export default function FileQueuePage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const { gstin, fp } = params;

  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listDocuments(gstin, fp);
        if (!cancelled) setRows(data.content);
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

  if (loading) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading documents…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Documents</h1>
        <Link
          href={`/app/upload/${gstin}/${fp}`}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          data-testid="upload-more"
        >
          + Upload
        </Link>
      </div>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period:{" "}
        <span className="font-mono">{fp}</span>
      </p>

      {error !== null && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {rows.length === 0 ? (
        <div className="mt-8 rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No documents yet.
          </p>
          <Link
            href={`/app/upload/${gstin}/${fp}`}
            className="mt-4 inline-block text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Upload your first invoice →
          </Link>
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {rows.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center justify-between rounded-lg border border-slate-200 p-4 dark:border-slate-800"
              data-testid="document-row"
            >
              <div>
                <p className="text-sm font-medium">{doc.doc_type}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {doc.capture_source} · {doc.page_count ?? 1} page
                  {doc.page_count === 1 ? "" : "s"}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <span className={`text-sm font-semibold ${statusColor(doc.job?.status ?? "UNKNOWN")}`}>
                  {doc.job?.status ?? "UNKNOWN"}
                </span>
                <Link
                  href={`/app/review/${gstin}/${fp}/${doc.id}`}
                  className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                  data-testid="review-link"
                >
                  Review →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
