"use client";

/**
 * Shell chrome shared by both role shells — FRONTEND_SPECIFICATION.md §1.
 * Linear / Vercel Minimalist Theme.
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { GstinRefDto } from "@/lib/api/client";

import { GstinSwitcher } from "./GstinSwitcher";

const DEFAULT_FP = "092026";

/** GSTIN-scoped workspaces: /app/<section>/<gstin>[/<fp>[/<docId>]]. */
const SCOPED_RE = /^\/app\/(?:upload|returns|file|einvoice|review|itc)\/([^/]+)(?:\/([^/]+))?/;

/** Sections the switcher may preserve when jumping to another GSTIN. */
const SWITCHER_SECTIONS = ["upload", "returns", "file", "einvoice", "itc"];

function gstinFromPath(pathname: string): string | null {
  const m = SCOPED_RE.exec(pathname);
  return m === null ? null : m[1];
}

function fpFromPath(pathname: string): string {
  const m = SCOPED_RE.exec(pathname);
  return m !== null && m[2] !== undefined ? m[2] : DEFAULT_FP;
}

function sectionFromPath(pathname: string): string {
  const section = pathname.split("/")[2] ?? "";
  return SWITCHER_SECTIONS.includes(section) ? section : "upload";
}

interface NavItem {
  key: string;
  label: string;
  href: string;
  isActive: (pathname: string) => boolean;
}

function SunIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 20 20" fill="currentColor">
      <path
        fillRule="evenodd"
        d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function MoonIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
    </svg>
  );
}

export function ShellNav({
  roleLabel,
  userName,
  onSignOut,
  gstAccounts = [],
}: {
  roleLabel: string;
  userName: string;
  onSignOut: () => void;
  gstAccounts?: GstinRefDto[];
}) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();

  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const updateTheme = () => {
      setIsDark(document.documentElement.classList.contains("dark"));
    };
    updateTheme();
    window.addEventListener("themechange", updateTheme);
    return () => window.removeEventListener("themechange", updateTheme);
  }, []);

  const toggleTheme = () => {
    const html = document.documentElement;
    const willBeDark = !html.classList.contains("dark");
    if (willBeDark) {
      html.classList.add("dark");
      try {
        localStorage.setItem("theme", "dark");
      } catch {}
    } else {
      html.classList.remove("dark");
      try {
        localStorage.setItem("theme", "light");
      } catch {}
    }
    setIsDark(willBeDark);
    window.dispatchEvent(new Event("themechange"));
  };

  const activeGstin = gstinFromPath(pathname) ?? gstAccounts[0]?.gstin ?? null;
  const fp = fpFromPath(pathname);

  const items: NavItem[] = [
    {
      key: "dashboard",
      label: "Dashboard",
      href: "/app",
      isActive: (p) => p === "/app" || p === "/app/" || p === "/",
    },
    {
      key: "businesses",
      label: "Businesses",
      href: "/app/businesses",
      isActive: (p) => p === "/app/businesses" || p.startsWith("/app/businesses/"),
    },
    ...(gstAccounts.length > 1
      ? [
          {
            key: "ca-clients",
            label: "Clients",
            href: "/ca",
            isActive: (p: string) => p === "/ca" || p.startsWith("/ca/"),
          },
        ]
      : []),
    {
      key: "upload",
      label: "Upload",
      href: activeGstin !== null ? `/app/upload/${activeGstin}/${fp}` : "/app",
      isActive: (p) => p.startsWith("/app/upload"),
    },
    {
      key: "returns",
      label: "Returns",
      href: activeGstin !== null ? `/app/returns/${activeGstin}/${fp}` : "/app",
      isActive: (p) => p.startsWith("/app/returns"),
    },
    {
      key: "file",
      label: "Filing",
      href: activeGstin !== null ? `/app/file/${activeGstin}/${fp}` : "/app",
      isActive: (p) => p.startsWith("/app/file"),
    },
    {
      key: "itc",
      label: "ITC",
      href: activeGstin !== null ? `/app/itc/${activeGstin}/${fp}` : "/app",
      isActive: (p) => p.startsWith("/app/itc"),
    },
    {
      key: "profile",
      label: "Profile",
      href: "/app/profile",
      isActive: (p) => p === "/app/profile" || p.startsWith("/app/profile/"),
    },
    {
      key: "settings",
      label: "Settings",
      href: "/app/settings",
      isActive: (p) => p === "/app/settings" || p.startsWith("/app/settings/"),
    },
  ];

  const switcherValue =
    activeGstin !== null && gstAccounts.some((a) => a.gstin === activeGstin)
      ? activeGstin
      : (gstAccounts[0]?.gstin ?? "");

  return (
    <nav className="relative z-40 border-b border-zinc-200/80 bg-white/95 backdrop-blur-md dark:border-white/[0.08] dark:bg-[#0c0d10]/95 transition-colors">
      <div className="flex h-14 items-center justify-between gap-x-4 px-4 sm:px-6">
        {/* Left: Brand + Role Badge */}
        <div className="flex shrink-0 items-center gap-2.5">
          <Link
            href="/app"
            className="text-base font-semibold tracking-tight text-zinc-900 hover:text-zinc-600 dark:text-zinc-100 dark:hover:text-white transition-colors"
          >
            GST Filing
          </Link>
          <span
            className="rounded-full border border-zinc-200 bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-600 dark:border-white/[0.1] dark:bg-white/[0.06] dark:text-zinc-300"
            data-testid="shell-role"
          >
            {roleLabel}
          </span>
        </div>

        {/* Center: Nav links */}
        <div
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-1 scrollbar-none"
          data-testid="shell-nav-links"
        >
          {items.map((item) => {
            const active = item.isActive(pathname);
            return (
              <Link
                key={item.key}
                href={item.href}
                data-testid={`nav-link-${item.key}`}
                aria-current={active ? "page" : undefined}
                className={
                  active
                    ? "shrink-0 rounded-md bg-zinc-100 px-2.5 py-1.5 text-sm font-medium text-zinc-900 dark:bg-white/[0.08] dark:text-zinc-100 dark:border dark:border-white/[0.08]"
                    : "shrink-0 rounded-md px-2.5 py-1.5 text-sm font-medium text-zinc-600 hover:bg-zinc-100/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/[0.04] dark:hover:text-zinc-200 transition-colors"
                }
              >
                {item.label}
              </Link>
            );
          })}
        </div>

        {/* Right: Switcher, User, Theme Toggle, Sign Out */}
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          {gstAccounts.length > 0 ? (
            <GstinSwitcher
              accounts={gstAccounts}
              value={switcherValue}
              onSelect={(g) => {
                if (g !== "") {
                  router.push(`/app/${sectionFromPath(pathname)}/${g}/${fp}`);
                }
              }}
            />
          ) : null}
          <span
            className="hidden text-sm font-medium text-zinc-600 dark:text-zinc-400 md:inline-block max-w-[130px] truncate"
            data-testid="shell-user"
            title={userName}
          >
            {userName}
          </span>
          <button
            type="button"
            onClick={toggleTheme}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-zinc-200 bg-transparent text-zinc-600 hover:bg-zinc-100 dark:border-white/[0.1] dark:text-zinc-400 dark:hover:bg-white/[0.06] dark:hover:text-zinc-200 transition-colors"
            title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            data-testid="theme-toggle-btn"
          >
            {isDark ? (
              <SunIcon className="h-4 w-4 text-amber-300" />
            ) : (
              <MoonIcon className="h-4 w-4 text-zinc-600" />
            )}
          </button>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded-md border border-zinc-200 bg-transparent px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-white/[0.1] dark:text-zinc-300 dark:hover:bg-white/[0.06] dark:hover:text-white transition-colors"
            data-testid="signout-btn"
          >
            Sign out
          </button>
        </div>
      </div>
    </nav>
  );
}
