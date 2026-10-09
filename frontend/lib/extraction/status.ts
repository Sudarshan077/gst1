"use client";

/**
 * Extraction pipeline status + poller — Task 9.2
 * (PHASE9_QA_SWEEP_FIXES.md §3.9.2, EXTRACTION_SPEC §10).
 *
 * The backend JobStatus enum (backend/app/db/models/extraction.py) is the
 * single source of truth: QUEUED → PREPROCESS → OCR_RUNNING → LLM_RUNNING →
 * EXTRACTED, with terminal outcomes EXTRACTED / NEEDS_REVIEW / FAILED /
 * CONFIRMED. (The QA doc's prose writes "PREPROCESSING/LLM_EXTRACTING";
 * the shipped backend values are PREPROCESS/LLM_RUNNING and those are what
 * we render — never invent status strings.)
 *
 * No new backend endpoints: the hook polls the existing GET /documents/{id}.
 */
import { useEffect, useState } from "react";

import { getDocument } from "@/lib/api/client";

/** Statuses at which the pipeline has finished and polling stops. */
export const TERMINAL_STATUSES = [
  "EXTRACTED",
  "NEEDS_REVIEW",
  "FAILED",
  "CONFIRMED",
] as const;

/** Ordered pipeline stages rendered as chips on the upload success card. */
export const PIPELINE_STAGES = [
  "QUEUED",
  "PREPROCESS",
  "OCR_RUNNING",
  "LLM_RUNNING",
  "EXTRACTED",
] as const;

/** Poll interval for a single document's extraction status (doc: 2s). */
const POLL_INTERVAL_MS = 2_000;
/** Hard cap so a stuck job cannot poll forever (doc: 5 minutes). */
const POLL_CAP_MS = 5 * 60_000;

export function isTerminalStatus(status: string | null | undefined): boolean {
  return (
    typeof status === "string" &&
    (TERMINAL_STATUSES as readonly string[]).includes(status)
  );
}

/** A draft exists and "Review / confirm" is meaningful for the user. */
export function isDraftReady(status: string | null | undefined): boolean {
  return (
    status === "EXTRACTED" || status === "NEEDS_REVIEW" || status === "CONFIRMED"
  );
}

export type StageState = "done" | "active" | "pending";

/** Visual state of one pipeline chip given the live job status. */
export function stageState(
  stage: (typeof PIPELINE_STAGES)[number],
  status: string,
): StageState {
  const stageIdx = (PIPELINE_STAGES as readonly string[]).indexOf(stage);
  // Any non-FAILED terminal outcome means the whole pipeline ran.
  if (isTerminalStatus(status) && status !== "FAILED") return "done";
  const idx = (PIPELINE_STAGES as readonly string[]).indexOf(status);
  if (idx === -1) return "pending"; // FAILED or UNKNOWN: nothing to highlight
  if (stageIdx < idx) return "done";
  if (stageIdx === idx) return "active";
  return "pending";
}

export interface ExtractionPollState {
  /** Live job status (seeded from the status captured at upload time). */
  status: string;
  /** True while the 2s poller is active (non-terminal, under the 5-min cap). */
  polling: boolean;
  /** True when polling stopped because the 5-minute cap was reached. */
  capped: boolean;
}

/**
 * Poll GET /documents/{docId} every 2s until the job reaches a terminal
 * status (EXTRACTED/NEEDS_REVIEW/FAILED/CONFIRMED), capped at 5 minutes.
 * Exactly one active interval per docId: it is cleared on unmount, on
 * docId change, on terminal status, and at the cap. Transient fetch
 * errors are ignored until the cap so a blip never freezes the card.
 */
export function useExtractionStatusPolling(
  docId: string | null,
  initialStatus: string,
): ExtractionPollState {
  const [state, setState] = useState<ExtractionPollState>({
    status: initialStatus,
    polling: false,
    capped: false,
  });

  useEffect(() => {
    const terminal = isTerminalStatus(initialStatus);
    // Re-seed on every docId change (a fresh upload replaces the card).
    setState({
      status: initialStatus,
      polling: docId !== null && !terminal,
      capped: false,
    });
    if (docId === null || terminal) return;

    const startedAt = Date.now();
    let busy = false;
    const timer = setInterval(() => {
      if (busy) return;
      if (Date.now() - startedAt >= POLL_CAP_MS) {
        clearInterval(timer);
        setState((s) => ({ ...s, polling: false, capped: true }));
        return;
      }
      busy = true;
      void (async () => {
        try {
          const doc = await getDocument(docId);
          const status = doc.job?.status ?? "UNKNOWN";
          if (isTerminalStatus(status)) {
            clearInterval(timer);
            setState({ status, polling: false, capped: false });
          } else {
            setState((s) => ({ ...s, status }));
          }
        } catch {
          // Transient error: keep the interval running; the cap stops it.
        } finally {
          busy = false;
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [docId, initialStatus]);

  return state;
}