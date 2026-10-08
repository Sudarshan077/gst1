#!/usr/bin/env python3
"""Phase-8 end-to-end verification (3-lens) — VERIFICATION_SWEEP.md applied
to PHASE8_PRODUCT_COMPLETENESS.md §3.8.11.

Three lenses, all with real command evidence (no summary-only PASS):

  Lens 1 — Code (backend correctness)
      Full pytest regression, ruff, mypy — every Phase-8 backend module is
      inside the full suite (profile/settings/returns_generate/business_mgmt).
      Money is integer paise: a hand-check of a money total on a fixture is
      asserted live inside test_returns_generate.py (the lens runs it).

  Lens 2 — Frontend / user flow
      tsc --noEmit, eslint, then the FULL Playwright suite (7.2 task7-2,
      auth-onboarding, phase4-filing, all five phase8-* specs, and the new
      phase8-product-shell reachability spec). Playwright boots the dev
      server itself (playwright.config.ts webServer).

  Lens 3 — GST domain correctness
      Runs the phase-relevant pytest modules for the hard rules:
        - test_critical_gstin.py    (mod-36 GSTIN checksum)
        - test_gstr1a.py            (423 locked-period contract)
        - test_returns_generate.py  (paise arithmetic, xlsx == JSON,
                                     hsn-summary reconciliation, validation)
        - test_gstr1.py             (GSTR-1 section math)
      Plus a static reachability audit: every Phase-8 route must be linked
      from the shell nav (ShellNav.tsx) — grep, not eyeball.

Usage:
    backend/.venv/Scripts/python.exe scripts/e2e_phase8.py

Exits 0 with a summary table if all gates pass, 1 on the first failure.
The Playwright lens requires PG:5436 + Redis:6380 + backend :8084
(scripts/bootstrap_stack.py; the frontend dev server is auto-booted).
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

PY = str(BACKEND / ".venv" / "Scripts" / "python.exe")

# Phase-8 backend modules — Lens 3 domain gate re-runs these explicitly;
# Lens 1 runs the whole tests/ tree including them.
PHASE8_MODULES = [
    "tests/test_profile_router.py",
    "tests/test_settings_router.py",
    "tests/test_business_mgmt_overview.py",
    "tests/test_returns_generate.py",
]

# Lens 3 — GST hard-rule modules (checksum, locked periods, paise math).
DOMAIN_MODULES = PHASE8_MODULES + [
    "tests/test_critical_gstin.py",
    "tests/test_gstr1a.py",
    "tests/test_gstr1.py",
]

# Every Phase-8 screen route; each must appear as a Link href (directly or
# via the nav item hrefs) in the shared shell. Static reachability audit.
PHASE8_ROUTES = [
    "/app/businesses",
    "/app/businesses/",  # detail: /app/businesses/<gstin>
    "/app/profile",
    "/app/settings",
    "/app/returns/",     # workspace: /app/returns/<gstin>/<fp>
    "/app",
]


def run(cmd, cwd, label, capture=True):
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    # Windows: npx/npm are .cmd shims that CreateProcess cannot launch
    # directly from Python without a shell.
    r = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=capture,
        text=True,
        shell=os.name == "nt",
        check=False,
    )
    tail = (r.stdout or "")[-1500:]
    if capture and tail.strip():
        print(tail)
    if capture and r.stderr and r.returncode != 0:
        print((r.stderr or "")[-1500:])
    print(f"exit {r.returncode} [{label}]")
    return r.returncode == 0


def lens1_code() -> bool:
    print("\n=== Lens 1: Code (backend correctness) ===")
    ok = True
    if not run(
        [PY, "-m", "pytest", "tests/", "-q", "--no-cov", "-p", "no:cacheprovider"],
        BACKEND,
        "Lens 1 full pytest",
    ):
        ok = False
        print("FAIL: full backend regression is not green")
    if not run([PY, "-m", "ruff", "check", "."], BACKEND, "Lens 1 ruff"):
        ok = False
        print("FAIL: ruff check failed")
    if not run([PY, "-m", "mypy", "app/"], BACKEND, "Lens 1 mypy"):
        ok = False
        print("FAIL: mypy app/ failed")
    return ok


def lens2_frontend() -> bool:
    print("\n=== Lens 2: Frontend / user flow ===")
    ok = True
    if not run(["npx", "tsc", "--noEmit"], FRONTEND, "Lens 2 tsc"):
        ok = False
        print("FAIL: tsc --noEmit failed")
    if not run(["npm", "run", "lint"], FRONTEND, "Lens 2 eslint"):
        ok = False
        print("FAIL: npm run lint failed")
    # Full Playwright suite: 7.2 (task7-2), auth-onboarding, phase4-filing,
    # all five phase8-* specs + the new phase8-product-shell spec.
    # playwright.config.ts boots the dev server on 9094 itself; the backend
    # (8084) + PG/Redis must already be up (bootstrap_stack.py).
    if not run(["npx", "playwright", "test"], FRONTEND, "Lens 2 playwright"):
        ok = False
        print("FAIL: Playwright suite is not green")
    return ok


def lens3_domain() -> bool:
    print("\n=== Lens 3: GST domain correctness ===")
    ok = True
    if not run(
        [PY, "-m", "pytest", *DOMAIN_MODULES, "-q", "--no-cov", "-p", "no:cacheprovider"],
        BACKEND,
        "Lens 3 domain modules",
    ):
        ok = False
        print("FAIL: domain module run failed")

    # Reachability audit: every Phase-8 route is linked from ShellNav.tsx.
    shell = (FRONTEND / "components" / "shared" / "ShellNav.tsx").read_text(
        encoding="utf-8"
    )
    missing = [r for r in PHASE8_ROUTES if r not in shell]
    if missing:
        ok = False
        print(f"FAIL: routes missing from ShellNav.tsx: {missing}")
    else:
        print(f"reachability audit: all {len(PHASE8_ROUTES)} route prefixes "
              "linked from ShellNav.tsx")
    return ok


def main() -> int:
    print("=== Phase-8 E2E: 3-lens verification ===")
    gates = [
        ("Lens 1 — Code (pytest/ruff/mypy)", lens1_code),
        ("Lens 2 — Frontend (tsc/lint/playwright)", lens2_frontend),
        ("Lens 3 — GST domain + reachability", lens3_domain),
    ]
    results = {}
    for name, fn in gates:
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001 — harness safety net
            print(f"EXCEPTION in {name}: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("PHASE-8 E2E RESULTS (3-lens)")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 60)
    if all(results.values()):
        print("ALL LENSES PASSED — Phase 8 E2E green")
        return 0
    print("SOME LENSES FAILED — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())