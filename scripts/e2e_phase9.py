#!/usr/bin/env python3
"""Phase-9 end-to-end verification (3-lens) — VERIFICATION_SWEEP.md applied
to PHASE9_QA_SWEEP_FIXES.md §3.9.6.

Three lenses, all with real command evidence (no summary-only PASS):

  Lens 1 — Code (backend correctness)
      Full pytest regression, ruff, mypy. Every Phase-9 backend surface is
      inside the full suite (extraction/validate.py WARN-tier rules in 9.5,
      services/itc_report.py + itc/report endpoint in 9.4, review confirm
      path in 9.1/9.5). Money is integer paise: a hand-check of a money total
      on a fixture is asserted live inside test_returns_generate.py.

  Lens 2 — Frontend / user flow
      tsc --noEmit, eslint, then the FULL Playwright suite (7.2 task7-2
      upload-to-output, auth-onboarding, phase4-filing, all seven phase8-*
      specs, and the six new phase9-* specs for 9.1–9.5). Playwright boots the
      dev server itself (playwright.config.ts webServer) and drives the real
      review/upload/itc screens.

  Lens 3 — GST domain correctness
      Re-runs the phase-relevant pytest modules for the hard rules:
        - test_critical_gstin.py     (mod-36 GSTIN checksum)
        - test_gstr1a.py             (423 locked-period contract)
        - test_gstr1.py              (GSTR-1 section math)
        - test_returns_generate.py   (paise arithmetic, xlsx == JSON,
                                      hsn-summary reconciliation, validation)
        - test_extraction_validator.py (9.5 WARN-tier advisory rules)
        - test_gstr2b_itc.py         (books vs 2B reconciliation engine, 9.4)
        - test_itc_report.py         (9.4 itc/report endpoint)
        - test_review_flow.py / test_review_service.py
                                      (9.1/9.5 confirm filters BLOCK only)
      Plus two static audits, grep-not-eyeball:
        (a) reachability — every phase-9 route (incl. the new /app/itc) is
            linked from the shared shell ShellNav.tsx;
        (b) spec coverage — frontend/tests/phase9-*.spec.ts exists for each of
            the 9.1, 9.2, 9.2B, 9.3, 9.4, 9.5 gates and is self-labelled.

Usage:
    backend/.venv/Scripts/python.exe scripts/e2e_phase9.py

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

# Phase-9 backend modules — Lens 3 domain gate re-runs these explicitly;
# Lens 1 runs the whole tests/ tree including them.
PHASE9_MODULES = [
    "tests/test_extraction_validator.py",  # 9.5 WARN-tier advisory rules
    "tests/test_itc_report.py",            # 9.4 itc/report endpoint
]

# Lens 3 — GST hard-rule modules (checksum, locked periods, paise math) plus
# the phase-9 review/ITC domain surfaces.
DOMAIN_MODULES = PHASE9_MODULES + [
    "tests/test_critical_gstin.py",
    "tests/test_gstr1a.py",
    "tests/test_gstr1.py",
    "tests/test_returns_generate.py",
    "tests/test_gstr2b_itc.py",
    "tests/test_review_flow.py",
    "tests/test_review_service.py",
]

# Every screen route reachable by clicking the shared shell nav. Each must
# appear as a Link href (directly or via the computed workspace hrefs) in
# ShellNav.tsx. Static reachability audit; "/app/itc/" is the 9.4 addition.
PHASE9_ROUTES = [
    "/app",
    "/app/businesses",
    "/app/businesses/",  # detail: /app/businesses/<gstin>
    "/app/profile",
    "/app/settings",
    "/app/upload/",       # workspace: /app/upload/<gstin>/<fp>
    "/app/returns/",      # workspace: /app/returns/<gstin>/<fp>
    "/app/itc/",          # 9.4: /app/itc/<gstin>/<fp>
]

# Phase-9 Playwright specs: task -> filename (+ the self-label the spec header
# carries, so "covers 9.x" is a checked fact, not an assumption).
PHASE9_SPECS = {
    "9.1": "phase9-review-editor.spec.ts",
    "9.2": "phase9-extraction-polling.spec.ts",
    "9.2B": "phase9-batch-upload.spec.ts",
    "9.3": "phase9-dashboard-empty-cta.spec.ts",
    "9.4": "phase9-itc-dashboard.spec.ts",
    "9.5": "phase9-review-advisory-warn.spec.ts",
}

# The Phase-8 reachability spec must survive the phase untouched.
LEGACY_REACHABILITY_SPEC = "phase8-product-shell.spec.ts"


def run(cmd, cwd, label, capture=True):
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    # Windows: npx/npm are .cmd shims that CreateProcess cannot launch
    # directly from Python without a shell.
    r = subprocess.run(  # noqa: S603 — fixed argv, no user-supplied command
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
        print("FAIL: ruff check failed (lint failures block)")
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
    # all seven phase8-* specs, and the six phase9-* specs (9.1–9.5).
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

    # (a) Reachability audit: every route is linked from ShellNav.tsx.
    shell = (FRONTEND / "components" / "shared" / "ShellNav.tsx").read_text(
        encoding="utf-8"
    )
    missing = [r for r in PHASE9_ROUTES if r not in shell]
    if missing:
        ok = False
        print(f"FAIL: routes missing from ShellNav.tsx: {missing}")
    else:
        print(f"reachability audit: all {len(PHASE9_ROUTES)} route prefixes "
              "linked from ShellNav.tsx (incl. /app/itc/)")

    # (b) Spec coverage: each phase-9 gate has its spec, self-labelled.
    tests_dir = FRONTEND / "tests"
    for task, fname in PHASE9_SPECS.items():
        path = tests_dir / fname
        if not path.exists():
            ok = False
            print(f"FAIL: missing phase-9 spec for {task}: tests/{fname}")
            continue
        text = path.read_text(encoding="utf-8")
        if f"Task {task} gate" not in text:
            ok = False
            print(f"FAIL: tests/{fname} does not self-label as 'Task {task} gate'")
        else:
            print(f"spec coverage: {task} -> tests/{fname}")
    if not (tests_dir / LEGACY_REACHABILITY_SPEC).exists():
        ok = False
        print(f"FAIL: {LEGACY_REACHABILITY_SPEC} (phase-8 reachability) was removed")
    return ok


def main() -> int:
    print("=== Phase-9 E2E: 3-lens verification ===")
    gates = [
        ("Lens 1 — Code (pytest/ruff/mypy)", lens1_code),
        ("Lens 2 — Frontend (tsc/lint/playwright)", lens2_frontend),
        ("Lens 3 — GST domain + reachability + spec coverage", lens3_domain),
    ]
    results = {}
    for name, fn in gates:
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001 — harness safety net
            print(f"EXCEPTION in {name}: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("PHASE-9 E2E RESULTS (3-lens)")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 60)
    if all(results.values()):
        print("ALL LENSES PASSED — Phase 9 E2E green")
        return 0
    print("SOME LENSES FAILED — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
