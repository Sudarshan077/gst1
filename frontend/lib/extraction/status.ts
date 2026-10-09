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
import { useEffect, useRef, useState } from "react";

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
  return (
    useExtractionStatusPollingMulti(docId === null ? null : [docId], {
      [docId ?? ""]: initialStatus,
    }).get(docId ?? "") ?? { status: initialStatus, polling: false, capped: false }
  );
}

/**
 * Batch variant (Task 9.2B): poll up to N documents at the same 2s cadence
 * with one shared interval and one shared 5-minute cap. Used by the upload
 * page's local batch queue so every queued row tracks its own job status.
 *
 * `initialStatuses` maps docId → status captured at upload time; ids that
 * are absent or already terminal are not polled. Ids with no live entry
 * (e.g. a row that never got a doc id because upload failed) resolve to the
 * caller-supplied fallback. The returned map always has one entry per id.
 */
export function useExtractionStatusPollingMulti(
  docIds: string[] | null,
  initialStatuses: Record<string, string>,
): Map<string, ExtractionPollState> {
  const ids = docIds === null ? [] : [...new Set(docIds)];
  const [states, setStates] = useState<Record<string, ExtractionPollState>>({});

  // The poller only needs to be rebuilt when the id set changes, not on
  // every render — keep the latest initial statuses in a ref.
  const initialRef = useRef<Record<string, string>>(initialStatuses);
  initialRef.current = initialStatuses;
  const key = ids.join(",");

  useEffect(() => {
    const current = key.length > 0 ? key.split(",") : [];
    const initial = initialRef.current;

    // Re-seed every id (a fresh upload replaces the whole queue).
    const seeded: Record<string, ExtractionPollState> = {};
    for (const id of current) {
      const status = initial[id] ?? "UNKNOWN";
      seeded[id] = {
        status,
        polling: !isTerminalStatus(status),
        capped: false,
      };
    }
    setStates(seeded);

    const live = current.filter((id) => !isTerminalStatus(seeded[id].status));
    if (live.length === 0) return;

    const startedAt = Date.now();
    const busy = new Set<string>();
    const timer = setInterval(() => {
      if (Date.now() - startedAt >= POLL_CAP_MS) {
        clearInterval(timer);
        setStates((prev) => {
          const next: Record<string, ExtractionPollState> = { ...prev };
          for (const id of live) {
            next[id] = { ...next[id], polling: false, capped: true };
          }
          return next;
        });
        return;
      }
      for (const id of live) {
        if (busy.has(id)) continue;
        busy.add(id);
        void (async () => {
          try {
            const doc = await getDocument(id);
            const status = doc.job?.status ?? "UNKNOWN";
            const terminal = isTerminalStatus(status);
            setStates((prev) => {
              const prevEntry = prev[id];
              // Stop touching an id once it is settled.
              if (!prevEntry || (!prevEntry.polling && !prevEntry.capped)) {
                return prev;
              }
              return {
                ...prev,
                [id]: { status, polling: !terminal, capped: false },
              };
            });
          } catch {
            // Transient error: keep the interval running; the cap stops it.
          } finally {
            busy.delete(id);
          }
        })();
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [key]);

  const out = new Map<string, ExtractionPollState>();
  for (const id of ids) {
    out.set(id, states[id] ?? { status: "UNKNOWN", polling: false, capped: false });
  }
  return out;
}