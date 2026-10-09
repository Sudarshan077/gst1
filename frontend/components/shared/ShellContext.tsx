"use client";

/**
 * Shell state shared from the (client)/app layout down to the pages that need
 * to keep the nav in sync — PHASE10_BUG_SWEEP_FIXES.md §10.2.
 *
 * The shared layout owns <ShellNav>; a page that mutates data the nav renders
 * (the profile rename, adding a GSTIN) pushes the change back through this
 * context so the header updates without a full reload — preserving the Phase-8
 * 8.6 / 8.8 behaviour that the per-page ShellNav used to provide.
 */
import { createContext, useContext } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { GstinRefDto } from "@/lib/api/client";

export interface ShellState {
  userName: string;
  gstAccounts: GstinRefDto[];
  setUserName: (name: string) => void;
  setGstAccounts: Dispatch<SetStateAction<GstinRefDto[]>>;
}

export const ShellContext = createContext<ShellState | null>(null);

/** The shell state, or null when rendered outside the (client)/app layout. */
export function useShell(): ShellState | null {
  return useContext(ShellContext);
}
