"use client";

/**
 * Searchable GSTIN switcher for the shell header.
 * Linear / Vercel Minimalist styling.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import type { GstinRefDto } from "@/lib/api/client";

interface GstinSwitcherProps {
  accounts: GstinRefDto[];
  /** Currently active GSTIN (the trigger label). */
  value: string;
  onSelect: (gstin: string) => void;
}

function ChevronDown() {
  return (
    <svg
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-zinc-500"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function GstinSwitcher({ accounts, value, onSelect }: GstinSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);

  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return accounts;
    return accounts.filter(
      (a) =>
        a.gstin.toLowerCase().includes(q) ||
        a.legal_name.toLowerCase().includes(q),
    );
  }, [accounts, query]);

  // Reset the highlighted row whenever the query changes.
  useEffect(() => {
    setHighlight(0);
  }, [query]);

  // Close on outside pointer-down.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // Focus the search input once opened.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setHighlight(0);
    const raf = requestAnimationFrame(() => searchRef.current?.focus());
    return () => cancelAnimationFrame(raf);
  }, [open]);

  const commit = (gstin: string) => {
    setOpen(false);
    setQuery("");
    onSelect(gstin);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[highlight];
      if (target) commit(target.gstin);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="gstin-switcher"
        aria-label="Active GSTIN"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex max-w-52 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-sm text-zinc-700 hover:bg-zinc-50 dark:border-white/[0.1] dark:bg-[#121215] dark:text-zinc-200 dark:hover:bg-white/[0.04] transition-colors"
      >
        <span className="truncate font-mono">{value || "Select GSTIN"}</span>
        <ChevronDown />
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-80 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-white/[0.12] dark:bg-[#141418] dark:shadow-2xl dark:shadow-black/80 backdrop-blur-md">
          <div className="border-b border-zinc-100 p-2.5 dark:border-white/[0.08]">
            <input
              ref={searchRef}
              type="text"
              data-testid="gstin-switcher-search"
              autoComplete="off"
              placeholder="Search GSTIN or business name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50/60 px-2.5 py-1.5 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-zinc-400 focus:bg-white focus:outline-none focus:ring-1 focus:ring-zinc-400/20 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus:border-white/[0.25]"
            />
          </div>
          <ul
            id="gstin-switcher-listbox"
            role="listbox"
            aria-label="GSTINs"
            className="max-h-64 overflow-auto py-1"
          >
            {filtered.length === 0 ? (
              <li className="px-3.5 py-2.5 text-sm text-zinc-500 dark:text-zinc-400">
                No GSTIN matches
              </li>
            ) : (
              filtered.map((a, i) => {
                const selected = a.gstin === value;
                const highlighted = i === highlight;
                return (
                  <li
                    key={a.gstin}
                    id={`gstin-switcher-option-${i}`}
                    role="option"
                    aria-selected={selected}
                    data-testid={`gstin-option-${a.gstin}`}
                    onMouseEnter={() => setHighlight(i)}
                    onClick={() => commit(a.gstin)}
                    className={`cursor-pointer px-3.5 py-2 transition-colors ${
                      highlighted
                        ? "bg-zinc-100/80 dark:bg-white/[0.06]"
                        : "bg-transparent"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-medium text-zinc-900 dark:text-zinc-100">
                        {a.gstin}
                      </span>
                      {selected ? (
                        <span className="rounded border border-zinc-200/60 bg-zinc-100 px-1.5 py-0.5 text-[11px] font-medium text-zinc-700 dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-zinc-300">
                          Active
                        </span>
                      ) : null}
                    </div>
                    {a.legal_name ? (
                      <div className="truncate text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                        {a.legal_name}
                      </div>
                    ) : null}
                  </li>
                );
              })
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
