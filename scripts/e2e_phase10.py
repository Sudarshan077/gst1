#!/usr/bin/env python3
"""Phase-10 end-to-end verification (3-lens) — VERIFICATION_SWEEP.md applied
to PHASE10_BUG_SWEEP_FIXES.md §10.5.

Three lenses, all with real command evidence (no summary-only PASS):

  Lens 1 — Code (backend correctness)
      Full pytest regression (--no-cov, the behaviour suite) AND the default
      addopts run WITH coverage, which is the 10.3 gate itself:
      `--cov=app --cov-fail-under=80` (no --no-cov escape). Then ruff, mypy.
      Money is integer paise: a hand-check of a money total on a fixture is
      asserted live inside test_returns_generate.py.

  Lens 2 — Frontend / user flow
      tsc --noEmit, eslint, then the FULL Playwright suite — now 33 tests:
      task7-2 upload-to-output, auth-onboarding, phase4-filing, all seven
      phase8-* specs, the six phase9-* specs, and the two NEW phase10 specs
      (phase10-shell-nav for 10.2, phase10-live-checksum for 10.4). Playwright
      boots the dev server itself (playwright.config.ts webServer).

  Lens 3 — GST domain correctness
      Re-runs the phase-relevant pytest modules for the hard rules:
        - test_gst_accounts.py       (10.1 FY rollover: exact 12-string fp list,
                                      current_fy_start_year April boundary)
        - test_critical_gstin.py     (mod-36 GSTIN checksum)
        - test_gstr1a.py             (423 locked-period contract)
        - test_gstr1.py              (GSTR-1 section math)
        - test_returns_generate.py   (paise arithmetic, xlsx == JSON, validation)
        - test_coverage_gate_targeted.py (10.3 targeted direct-call tests)
      Plus static audits, grep-not-eyeball, verifying the four 10.x fixes:
        (a) 10.1 — the source no longer builds the FY grid with range(4, 16);
        (b) 10.2 — the shared (client)/app layout renders <ShellNav> exactly
            once, no page under (client)/app renders it (no double header), and
            every workspace route directory lives under that shared layout;
        (c) 10.3 — the coverage-gate targeted test module exists;
        (d) 10.4 — the live-error testid + gstinChecksumValid wiring exist;
        (e) route reachability — every shell nav prefix is linked from
            ShellNav.tsx (incl. the workspace routes upload/returns/itc);
        (f) spec coverage — the two phase10-*.spec.ts exist and self-label
            ('Task 10.2 gate' / 'Task 10.4 gate') and the phase9-* specs survive.

Usage:
    backend/.venv/Scripts/python.exe scripts/e2e_phase10.py

Exits 0 with a summary table if all gates pass, 1 on the first failure.
The Playwright lens requires PG:5436 + Redis:6380 + backend :8084
(scripts/bootstrap_stack.py; the frontend dev server is auto-booted).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
CLIENT_APP = FRONTEND / "app" / "(client)" / "app"
SHELL_NAV = FRONTEND / "components" / "shared" / "ShellNav.tsx"
SHARED_LAYOUT = CLIENT_APP / "layout.tsx"

PY = str(BACKEND / ".venv" / "Scripts" / "python.exe")

# Phase-10 backend modules — Lens 3 re-runs these explicitly; Lens 1 runs the
# whole tests/ tree including them.
PHASE10_MODULES = [
    "tests/test_gst_accounts.py",           # 10.1 FY rollover
    "tests/test_coverage_gate_targeted.py",  # 10.3 targeted coverage tests
]

# Lens 3 — GST hard-rule modules (checksum, locked periods, paise math) plus
# the phase-10 domain surfaces.
DOMAIN_MODULES = PHASE10_MODULES + [
    "tests/test_critical_gstin.py",
    "tests/test_gstr1a.py",
    "tests/test_gstr1.py",
    "tests/test_returns_generate.py",
]

# Every screen route reachable by clicking the shared shell nav. Each must
# appear in ShellNav.tsx (directly or via the computed workspace hrefs).
PHASE10_ROUTES = [
    "/app",
    "/app/businesses",
    "/app/businesses/",   # detail: /app/businesses/<gstin>
    "/app/profile",
    "/app/settings",
    "/app/upload/",       # workspace: /app/upload/<gstin>/<fp>
    "/app/returns/",      # workspace: /app/returns/<gstin>/<fp>
    "/app/itc/",          # workspace: /app/itc/<gstin>/<fp>
]

# The six workspace sections that must live under the shared (client)/app
# layout so the shell nav renders on them (10.2). Directory names under
# frontend/app/(client)/app/.
WORKSPACE_SECTIONS = ["upload", "returns", "review", "einvoice", "file", "itc"]

# Phase-10 Playwright specs: task -> filename (+ the self-label the spec header
# carries, so "covers 10.x" is a checked fact, not an assumption).
PHASE10_SPECS = {
    "10.2": ("phase10-shell-nav.spec.ts", "Task 10.2 gate"),
    "10.4": ("phase10-live-checksum.spec.ts", "Task 10.4 gate"),
}

# Phase-9 specs that must survive the sweep untouched.
LEGACY_PHASE9_SPECS = [
    "phase9-review-editor.spec.ts",
    "phase9-extraction-polling.spec.ts",
    "phase9-batch-upload.spec.ts",
    "phase9-dashboard-empty-cta.spec.ts",
    "phase9-itc-dashboard.spec.ts",
    "phase9-review-advisory-warn.spec.ts",
    "phase8-product-shell.spec.ts",
]


def run(cmd, cwd, label, grep=None):
    """Run a command; return True on exit 0. `grep` = list of regexes whose
    matching stdout lines are echoed (evidence for coverage/summary lines)."""
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    # Windows: npx/npm are .cmd shims that CreateProcess cannot launch
    # directly from Python without a shell.
    r = subprocess.run(  # noqa: S603 — fixed argv, no user-supplied command
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=os.name == "nt",
        check=False,
    )
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    if grep:
        for pat in grep:
            for line in out.splitlines():
                if re.search(pat, line):
                    print(line.strip())
    tail = out[-1200:]
    if tail.strip():
        print(tail)
    print(f"exit {r.returncode} [{label}]")
    return r.returncode == 0


def strip_ts_comments(src: str) -> str:
    """Drop /* ... */ block comments and // line comments from TS/TSX source.

    The 10.2 audit counts "<ShellNav>" JSX renders; a docblock that merely
    *mentions* <ShellNav> must not be miscounted, so comments are removed
    before the regex runs. Good enough for this repo's source (no string
    literals containing comment markers).
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def lens1_code() -> bool:
    print("\n=== Lens 1: Code (backend correctness) ===")
    ok = True
    # Behaviour suite (fast, no coverage).
    if not run(
        [PY, "-m", "pytest", "tests/", "-q", "--no-cov", "-p", "no:cacheprovider"],
        BACKEND,
        "Lens 1 full pytest (no-cov)",
        grep=[r"\d+ passed", r"\d+ failed"],
    ):
        ok = False
        print("FAIL: full backend behaviour regression is not green")
    # 10.3 gate: the DEFAULT addopts run, which enforces --cov-fail-under=80.
    if not run(
        [PY, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
        BACKEND,
        "Lens 1 coverage gate (--cov-fail-under=80)",
        grep=[r"Required test coverage", r"^TOTAL", r"\d+ passed", r"\d+ failed"],
    ):
        ok = False
        print("FAIL: pytest with the default addopts did not reach the 80% gate")
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
    # Full Playwright suite: task7-2, auth-onboarding, phase4-filing, all seven
    # phase8-* specs, the six phase9-* specs, and the two phase10-* specs.
    # playwright.config.ts boots the dev server on 9094 itself; the backend
    # (8084) + PG/Redis must already be up (bootstrap_stack.py).
    if not run(
        ["npx", "playwright", "test"],
        FRONTEND,
        "Lens 2 playwright",
        grep=[r"\d+ passed", r"\d+ failed", r"\d+ flaky"],
    ):
        ok = False
        print("FAIL: Playwright suite is not green")
    return ok


def lens3_domain() -> bool:
    print("\n=== Lens 3: GST domain correctness + phase-10 fix audits ===")
    ok = True
    if not run(
        [PY, "-m", "pytest", *DOMAIN_MODULES, "-q", "--no-cov", "-p", "no:cacheprovider"],
        BACKEND,
        "Lens 3 domain modules",
        grep=[r"\d+ passed", r"\d+ failed"],
    ):
        ok = False
        print("FAIL: domain module run failed")

    # (a) 10.1 — the FY grid must no longer be built with range(4, 16).
    service = (BACKEND / "app" / "core" / "gst_accounts" / "service.py").read_text(
        encoding="utf-8"
    )
    if "range(4, 16)" in service:
        ok = False
        print("FAIL [10.1]: gst_accounts/service.py still builds the FY grid "
              "with range(4, 16)")
    elif "range(4, 13)" not in service or "range(1, 4)" not in service:
        ok = False
        print("FAIL [10.1]: fy_periods_for_year does not use range(4, 13) + "
              "range(1, 4)")
    else:
        print("10.1 audit: FY grid is range(4, 13) + range(1, 4) — no month "
              "index 13/14/15 constructible")

    # (b) 10.2 — the shared layout renders <ShellNav> exactly once; no page
    # under (client)/app renders it (no double header); every workspace section
    # lives under that shared layout. Comments are stripped first so a docblock
    # mention of "<ShellNav>" is not miscounted as a render.
    layouts = sorted(CLIENT_APP.rglob("layout.tsx"))
    if layouts != [SHARED_LAYOUT]:
        ok = False
        print(f"FAIL [10.2]: expected exactly one layout under (client)/app "
              f"({SHARED_LAYOUT}); found {layouts}")
    layout_src = strip_ts_comments(SHARED_LAYOUT.read_text(encoding="utf-8"))
    n_layout_nav = len(re.findall(r"<ShellNav\b", layout_src))
    if n_layout_nav != 1:
        ok = False
        print(f"FAIL [10.2]: shared layout renders <ShellNav> {n_layout_nav}x "
              "(expected exactly 1)")
    page_renders = []
    for page in CLIENT_APP.rglob("page.tsx"):
        txt = strip_ts_comments(page.read_text(encoding="utf-8"))
        if re.search(r"<ShellNav\b", txt):
            page_renders.append(str(page.relative_to(FRONTEND)))
    if page_renders:
        ok = False
        print(f"FAIL [10.2]: page(s) still render <ShellNav> (double header): "
              f"{page_renders}")
    missing_sections = [
        s for s in WORKSPACE_SECTIONS if not (CLIENT_APP / s).is_dir()
    ]
    if missing_sections:
        ok = False
        print(f"FAIL [10.2]: workspace section dir(s) missing under (client)/app: "
              f"{missing_sections}")
    if ok:
        print("10.2 audit: single (client)/app layout renders <ShellNav> once; "
              "0 page.tsx duplicates; workspace sections present -> "
              f"{WORKSPACE_SECTIONS}")

    # (c) 10.3 — the coverage-gate targeted test module exists.
    targeted = BACKEND / "tests" / "test_coverage_gate_targeted.py"
    if not targeted.exists():
        ok = False
        print("FAIL [10.3]: tests/test_coverage_gate_targeted.py is missing")
    else:
        print("10.3 audit: tests/test_coverage_gate_targeted.py present "
              f"({targeted.stat().st_size} bytes)")

    # (d) 10.4 — the live-error testid + live checksum wiring exist, and the
    # pre-existing business-add-* testids are preserved.
    businesses = (CLIENT_APP / "businesses" / "page.tsx").read_text(encoding="utf-8")
    need_104 = (
        "business-add-live-error",
        "gstinChecksumValid(gstinDraft)",
        "business-add-gstin",
        "business-add-name",
        "business-add-submit",
        "business-add-error",
    )
    missing_104 = [n for n in need_104 if n not in businesses]
    if missing_104:
        ok = False
        print(f"FAIL [10.4]: businesses/page.tsx is missing {missing_104}")
    else:
        print("10.4 audit: businesses/page.tsx carries the live mod-36 error "
              "(business-add-live-error + gstinChecksumValid(gstinDraft)) and "
              "keeps all business-add-* testids")

    # (e) Reachability audit: every shell nav prefix is linked from ShellNav.tsx.
    shell = SHELL_NAV.read_text(encoding="utf-8")
    missing = [r for r in PHASE10_ROUTES if r not in shell]
    if missing:
        ok = False
        print(f"FAIL: routes missing from ShellNav.tsx: {missing}")
    else:
        print(f"reachability audit: all {len(PHASE10_ROUTES)} route prefixes "
              "linked from ShellNav.tsx (incl. workspace upload/returns/itc)")

    # (f) Spec coverage: the two phase10 specs exist and self-label; phase-9
    # specs survive.
    tests_dir = FRONTEND / "tests"
    for task, (fname, label) in PHASE10_SPECS.items():
        path = tests_dir / fname
        if not path.exists():
            ok = False
            print(f"FAIL: missing phase-10 spec for {task}: tests/{fname}")
            continue
        if label not in path.read_text(encoding="utf-8"):
            ok = False
            print(f"FAIL: tests/{fname} does not self-label as {label!r}")
        else:
            print(f"spec coverage: {task} -> tests/{fname} (self-labelled {label!r})")
    for fname in LEGACY_PHASE9_SPECS:
        if not (tests_dir / fname).exists():
            ok = False
            print(f"FAIL: {fname} (phase-8/9 regression spec) was removed")
    return ok


def main() -> int:
    print("=== Phase-10 E2E: 3-lens verification ===")
    gates = [
        ("Lens 1 — Code (pytest/coverage-gate/ruff/mypy)", lens1_code),
        ("Lens 2 — Frontend (tsc/lint/playwright)", lens2_frontend),
        ("Lens 3 — GST domain + reachability + fix audits", lens3_domain),
    ]
    results = {}
    for name, fn in gates:
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001 — harness safety net
            print(f"EXCEPTION in {name}: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("PHASE-10 E2E RESULTS (3-lens)")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 60)
    if all(results.values()):
        print("ALL LENSES PASSED — Phase 10 E2E green")
        return 0
    print("SOME LENSES FAILED — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
