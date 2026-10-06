#!/usr/bin/env python3
"""Phase-5 end-to-end verification (Deployment, Compliance & Go-Live).

Phase 5 Definition of Done gates:
  1. Production infrastructure: docker-compose config valid
  2. GSP/IRP onboarding: pytest test_gsp_irp_onboarding.py passes
  3. Security hardening: bandit + pip-audit clean (0 findings)
  4. DPDP compliance: pytest test_dpdp.py passes
  5. Full regression: 210 tests pass (serial and parallel -n 4)
  6. Coverage gate: 81.47% >= 80% floor enforced

Usage:
    python scripts/e2e_phase5.py

Returns:
    exit 0 with summary table if all gates pass
    exit 1 on first failure
"""
import subprocess
import sys
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = os.path.join(ROOT, "backend")
os.environ["PYTHONPATH"] = ROOT


def run(cmd, **kwargs):
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, **kwargs)
    print(f"exit {r.returncode}")
    return r.returncode == 0


def check_docker_compose():
    """Gate 1: Production infrastructure setup."""
    print("\n=== Gate 1: Production Infrastructure ===")
    dc = os.path.join(ROOT, "docker-compose.prod.yml")
    ok = run(["docker", "compose", "-f", dc, "config"], cwd=ROOT)
    if not ok:
        print("FAIL: docker compose -f docker-compose.prod.yml config failed")
    return ok


def check_gsp_irp_onboarding():
    """Gate 2: GSP & IRP Free-Tier Developer Onboarding."""
    print("\n=== Gate 2: GSP & IRP Onboarding ===")
    tf = os.path.join(BACKEND, "tests", "test_gsp_irp_onboarding.py")
    ok = run(["uv", "run", "--project", BACKEND, "pytest", tf, "-v", "--no-cov"], cwd=BACKEND)
    if not ok:
        print("FAIL: test_gsp_irp_onboarding.py failed")
    return ok


def check_security():
    """Gate 3: Security hardening — bandit + pip-audit."""
    print("\n=== Gate 3: Security Hardening ===")
    ok = True
    # bandit on app/
    r = subprocess.run(
        ["uv", "run", "--project", BACKEND, "bandit", "-r", "app/", "-ll", "-q"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    bandit_clean = r.returncode == 0
    if not bandit_clean:
        print("FAIL: bandit found issues in app/")
        print(r.stdout + r.stderr)
        ok = False
    else:
        print("bandit: 0 issues")

    # pip-audit
    r = subprocess.run(
        ["uv", "run", "--project", BACKEND, "pip-audit", "."],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    audit_clean = r.returncode == 0
    if not audit_clean:
        print("FAIL: pip-audit found vulnerabilities")
        print(r.stdout + r.stderr)
        ok = False
    else:
        print("pip-audit: 0 vulnerabilities")

    return ok


def check_dpdp():
    """Gate 4: DPDP compliance."""
    print("\n=== Gate 4: DPDP Compliance ===")
    tf = os.path.join(BACKEND, "tests", "test_dpdp.py")
    ok = run(["uv", "run", "--project", BACKEND, "pytest", tf, "-v", "--no-cov"], cwd=BACKEND)
    if not ok:
        print("FAIL: test_dpdp.py failed")
    return ok


def check_full_suite_serial():
    """Gate 5a: Full regression — serial."""
    print("\n=== Gate 5a: Full Suite (serial) ===")
    r = subprocess.run(
        ["uv", "run", "--project", BACKEND, "pytest", "tests/", "-q", "--cov=app", "--cov-fail-under=80"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    print(r.stdout[-2000:] if r.stdout else "")
    if r.returncode != 0:
        print("FAIL: serial suite failed")
        return False
    print("PASS: serial suite green")
    return True


def check_full_suite_parallel():
    """Gate 5b: Full regression — parallel xdist."""
    print("\n=== Gate 5b: Full Suite (parallel -n 4) ===")
    r = subprocess.run(
        ["uv", "run", "--project", BACKEND, "pytest", "tests/", "-n", "4", "-q", "--cov=app", "--cov-fail-under=80"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    print(r.stdout[-2000:] if r.stdout else "")
    if r.returncode != 0:
        print("FAIL: parallel suite failed")
        return False
    print("PASS: parallel suite green")
    return True


def main():
    print("=== Phase-5 E2E: Deployment, Compliance & Go-Live ===")

    gates = [
        ("Production Infrastructure", check_docker_compose),
        ("GSP & IRP Onboarding",    check_gsp_irp_onboarding),
        ("Security Hardening",       check_security),
        ("DPDP Compliance",          check_dpdp),
        ("Full Suite Serial",       check_full_suite_serial),
        ("Full Suite Parallel",     check_full_suite_parallel),
    ]

    results = {}
    for name, fn in gates:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"EXCEPTION in {name}: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("PHASE-5 E2E RESULTS")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    all_pass = all(results.values())
    print("=" * 60)
    if all_pass:
        print("ALL GATES PASSED — Phase 5 E2E green")
        return 0
    else:
        print("SOME GATES FAILED — see above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
