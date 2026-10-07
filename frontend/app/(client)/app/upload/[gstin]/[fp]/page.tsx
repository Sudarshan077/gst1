"use client";

/**
 * Upload page — the entry to the upload-to-output happy path (Task 7.2).
 * User picks a capture source, drops/uploads a file, and the backend stores
 * it, spawns an extraction job, then starts polling the document status.
 */
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import {
  ApiError,
  getDocument,
  triggerExtraction,
  uploadDocument,
  UploadResult,
} from "@/lib/api/client";

type CaptureSource = "PDF_SCAN" | "DIGITAL" | "PHOTO" | "WHATSAPP";

const CAPTURE_LABELS: Record<CaptureSource, string> = {
  PDF_SCAN: "PDF scan",
  DIGITAL: "Native PDF / digital",
  PHOTO: "Phone photo",
  WHATSAPP: "WhatsApp photo",
};

export default function UploadPage() {
  const params = useParams<{ gstin: string; fp: string }>();
  const router = useRouter();
  const { gstin, fp } = params;

  const [captureSource, setCaptureSource] = useState<CaptureSource>("PDF_SCAN");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  function handleFile(selected: File | null) {
    if (selected) {
      setFile(selected);
      setError(null);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (file === null) {
      setError("choose a file to upload");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const res = await uploadDocument(gstin, fp, captureSource, file);
      try {
        await triggerExtraction(res.id);
        const detail = await getDocument(res.id);
        setResult({ ...res, job: detail.job });
      } catch {
        setResult(res);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold">Upload invoice / statement</h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        GSTIN: <span className="font-mono">{gstin}</span> · Period:{" "}
        <span className="font-mono">{fp}</span>
      </p>

      <form onSubmit={submit} className="mt-8 space-y-6">
        <div>
          <label className="block text-sm font-medium">Capture source</label>
          <select
            value={captureSource}
            onChange={(e) => setCaptureSource(e.target.value as CaptureSource)}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="capture-source"
          >
            {(Object.keys(CAPTURE_LABELS) as CaptureSource[]).map((k) => (
              <option key={k} value={k}>
                {CAPTURE_LABELS[k]}
              </option>
            ))}
          </select>
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFile(e.dataTransfer.files[0] ?? null);
          }}
          className={`
            cursor-pointer rounded-xl border-2 border-dashed p-10 text-center
            ${dragOver ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30" : "border-slate-300 dark:border-slate-700"}
          `}
        >
          <input
            type="file"
            accept=".pdf,image/jpeg,image/png"
            className="hidden"
            id="file-input"
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            data-testid="file-input"
          />
          <label htmlFor="file-input" className="cursor-pointer">
            {file === null ? (
              <>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Drag & drop a PDF or image, or click to browse
                </p>
                <p className="mt-2 text-xs text-slate-400">
                  PDF, JPG, PNG · max 25 MB
                </p>
              </>
            ) : (
              <p className="text-sm font-medium text-indigo-700 dark:text-indigo-300">
                {file.name}
              </p>
            )}
          </label>
        </div>

        <button
          type="submit"
          disabled={uploading || file === null}
          className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          data-testid="upload-submit"
        >
          {uploading ? "Uploading…" : "Upload & extract"}
        </button>
      </form>

      {error !== null && (
        <p
          className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
          role="alert"
          data-testid="upload-error"
        >
          {error}
        </p>
      )}

      {result !== null && (
        <div
          className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950"
          data-testid="upload-success"
        >
          <p className="text-sm font-medium text-green-800 dark:text-green-200">
            Uploaded
          </p>
          <p className="mt-1 text-xs text-green-700 dark:text-green-300">
            Document ID: {result.id}
          </p>
          <p className="text-xs text-green-700 dark:text-green-300">
            Status: {result.job?.status ?? "UNKNOWN"}
          </p>
          <button
            type="button"
            onClick={() => router.push(`/app/file/${gstin}/${fp}`)}
            className="mt-3 rounded-md bg-green-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-800"
            data-testid="go-to-queue"
          >
            Review / confirm →
          </button>
        </div>
      )}
    </main>
  );
}
