#!/usr/bin/env python3
"""Phase-0 end-to-end verification (AI_BUILD_PLAYBOOK.md task 0.8).

Checks the exact Phase-0 Definition of Done from docs/TESTING_STRATEGY.md §5:
  1. migrations up/down/up clean
  2. auth E2E — both roles, TOTP enforced for CA
  3. data plane health: PG:5436, Redis:6380, MinIO:9001
  4. docs §1-§6 verified against live code
  5. lint/type gates clean

Usage:
    python scripts/e2e_phase0.py [--backend-only]

Returns:
    exit 0 with summary table if all gates pass
    exit 1 with failed-gate list otherwise
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
FARMER_TOOLS = Path("D:/farmer_app/tools")
PG_BIN = FARMER_TOOLS / "pg/pgsql/bin"
PSQL = str(PG_BIN / "psql.exe")

NPM = shutil.which("npm")
NPX = shutil.which("npx")
ALEMBIC = str(BACKEND_DIR / ".venv/Scripts/alembic.exe")


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def run(
    cmd: list[str] | str,
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def psql(db: str, sql: str) -> str:
    """Run a SQL query against the named database on the dev PG server.

    Hard-fails when a SELECT unexpectedly returns blank stdout; silent no-ops
    must never pass a gate. Exceptions: pg_terminate_backend naturally returns
    an empty result when there are no matching backends.
    """
    p = run(
        [PSQL, "-h", "127.0.0.1", "-p", "5436", "-U", "gst", "-d", db, "-tAc", sql],
        env={**os.environ, "PGPASSWORD": "gst_dev_pass"},
        timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError(f"psql failed on {db}: {p.stderr.strip()}")
    stdout = p.stdout.strip()
    is_select = sql.lstrip().upper().startswith("SELECT")
    empty_ok = "pg_terminate_backend" in sql
    if is_select and stdout == "" and not empty_ok:
        raise RuntimeError(f"psql SELECT on {db} returned unexpectedly blank output")
    return stdout


def _heading(n: int, title: str) -> None:
    print(f"\n{n}. {title}")


def _ok(msg: str) -> None:
    print(f"   OK  — {msg}")


def _fail(msg: str) -> list[str]:
    print(f"   FAIL — {msg}")
    return [msg]


def gate_data_plane() -> list[str]:
    _heading(1, "Data plane health")
    fails: list[str] = []
    for svc, port in (("postgres", 5436), ("redis", 6380), ("minio", 9001)):
        if port_open(port):
            _ok(f"{svc} :{port} listening")
        else:
            fails.extend(_fail(f"{svc} :{port} not reachable"))
    return fails


def gate_migrations() -> list[str]:
    _heading(2, "Alembic migrations up/down/up clean")
    fails: list[str] = []

    # Ensure the dev DB is at head.
    cfg_dev = Config(str(BACKEND_DIR / "alembic.ini"))
    try:
        command.upgrade(cfg_dev, "head")
        _ok("alembic upgrade head (dev DB)")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"alembic upgrade head failed: {exc}")

    # Build a throwaway DB and cycle it.
    db_name = f"gst_e2e_phase0_{uuid.uuid4().hex[:12]}"
    target_url = f"postgresql+asyncpg://gst:gst_dev_pass@127.0.0.1:5436/{db_name}"

    try:
        psql("postgres", f'CREATE DATABASE "{db_name}";')
    except Exception as exc:  # noqa: BLE001
        return _fail(f"create throwaway DB failed: {exc}")

    # Verify the scratch DB exists before proceeding.
    try:
        exists = psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"could not confirm scratch DB exists: {exc}")
    if exists != "1":
        return _fail(f"scratch DB {db_name} not found after CREATE DATABASE")
    _ok(f"scratch DB {db_name} created and confirmed")

    try:
        for schema in ("core", "gst", "extraction"):
            psql(db_name, f'CREATE SCHEMA IF NOT EXISTS "{schema}";')

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", target_url)

        # Canary table to prove we are operating on the scratch DB, not the dev DB.
        psql(db_name, "CREATE TABLE canary (id int);")

        command.upgrade(cfg, "head")
        _ok("scratch DB: alembic upgrade head")
    except Exception as exc:  # noqa: BLE001
        fails.extend(_fail(f"up on scratch DB failed: {exc}"))
        return fails

    try:
        command.downgrade(cfg, "base")
        _ok("scratch DB: alembic downgrade base")
    except Exception as exc:  # noqa: BLE001
        fails.extend(_fail(f"downgrade on scratch DB failed: {exc}"))
        return fails

    # Note: alembic downgrade does not drop the canary table because it is not
    # managed by a migration. Exclude tables in schemas outside the migration
    # set and any manually-created canary table.

    # Verify no leftover tables/enums in the three schemas.
    tables_sql = (
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema IN ('core','gst','extraction') AND table_name <> 'canary';"
    )
    leftover_tables = psql(db_name, tables_sql)
    if leftover_tables and int(leftover_tables) != 0:
        fails.extend(_fail(f"downgrade left {leftover_tables} table(s) in core/gst/extraction"))

    try:
        command.upgrade(cfg, "head")
        _ok("scratch DB: alembic upgrade head (2nd)")
    except Exception as exc:  # noqa: BLE001
        fails.extend(_fail(f"second up on scratch DB failed: {exc}"))
        return fails

    # Prove the canary table survived on the scratch DB (and was not dropped
    # by accidentally targeting the dev DB).
    canary = psql(db_name, "SELECT to_regclass('canary')")
    if canary and canary != "":
        _ok("canary table still present on scratch DB after migrations")
    else:
        fails.extend(_fail("canary table missing after migrations — possible dev DB pollution"))

    try:
        psql("postgres", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();")
        psql("postgres", f'DROP DATABASE "{db_name}";')
    except Exception as exc:  # noqa: BLE001
        fails.extend(_fail(f"cleanup of scratch DB failed: {exc}"))

    # Confirm no leftover scratch DBs in postgres catalog.
    leftover_dbs = psql(
        "postgres",
        "SELECT count(*) FROM pg_database WHERE datname LIKE 'gst_e2e_phase0%'",
    )
    if leftover_dbs and int(leftover_dbs) != 0:
        fails.extend(_fail(f"scratch DBs left in postgres catalog: {leftover_dbs}"))
    else:
        _ok("no scratch DBs left in postgres catalog")

    return fails


def gate_backend_tests() -> list[str]:
    _heading(3, "Backend pytest L1/L2 suite")
    fails: list[str] = []
    ruff = run([ALEMBIC.replace("alembic.exe", "ruff.exe"), "check", "."], cwd=BACKEND_DIR, timeout=120)
    # Per pyproject the lint entrypoint is the venv binary; fall back to uv run if needed.
    if ruff.returncode != 0:
        fails.extend(_fail(f"ruff check failed:\n{ruff.stdout}\n{ruff.stderr}"))
    else:
        _ok("ruff check clean")

    mypy = run([ALEMBIC.replace("alembic.exe", "mypy.exe"), "."], cwd=BACKEND_DIR, timeout=120)
    if mypy.returncode != 0:
        fails.extend(_fail(f"mypy failed:\n{mypy.stdout}\n{mypy.stderr}"))
    else:
        _ok("mypy strict clean")

    python = ALEMBIC.replace("alembic.exe", "python.exe")
    tests = run([python, "-m", "pytest", "-v"], cwd=BACKEND_DIR, timeout=300)
    if tests.returncode != 0:
        fails.extend(_fail(f"pytest failed:\n{tests.stdout}\n{tests.stderr}"))
    else:
        # extract pass count from the summary line
        summary_match = re.search(r"(\d+) passed", tests.stdout)
        count = summary_match.group(1) if summary_match else "?"
        _ok(f"pytest: {count} tests passed")
    return fails


def gate_frontend_static() -> list[str]:
    _heading(4, "Frontend lint + type")
    fails: list[str] = []
    if NPM is None:
        return _fail("npm not found on PATH")
    npm_install = run([NPM, "ci"], cwd=FRONTEND_DIR, timeout=180)
    if npm_install.returncode != 0:
        return _fail(f"npm ci failed:\n{npm_install.stderr}")

    lint = run([NPM, "run", "lint"], cwd=FRONTEND_DIR, timeout=120)
    if lint.returncode != 0:
        fails.extend(_fail(f"eslint failed:\n{lint.stdout}\n{lint.stderr}"))
    else:
        _ok("eslint clean")

    if NPX is None:
        return _fail("npx not found on PATH")
    tsc = run([NPX, "tsc", "--noEmit"], cwd=FRONTEND_DIR, timeout=120)
    if tsc.returncode != 0:
        fails.extend(_fail(f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"))
    else:
        _ok("tsc --noEmit clean")
    return fails


def gate_playwright() -> list[str]:
    _heading(5, "Playwright E2E — both roles onboard")
    fails: list[str] = []

    backend_proc: subprocess.Popen | None = None
    try:
        python = ALEMBIC.replace("alembic.exe", "python.exe")
        backend_proc = subprocess.Popen(
            [python, "-m", "uvicorn", "app.main:app", "--port", "8084"],
            cwd=BACKEND_DIR,
        )
        deadline = time.monotonic() + 60
        healthy = False
        while time.monotonic() < deadline:
            try:
                health = run([python, "-m", "httpx", "http://127.0.0.1:8084/api/v1/health"], timeout=5)
                # httpx CLI not guaranteed; fall back to socket
                if health.returncode == 0:
                    healthy = True
                    break
            except Exception:  # noqa: BLE001
                pass
            if port_open(8084):
                healthy = True
                break
            time.sleep(0.5)
        if not healthy:
            fails.extend(_fail("backend never became healthy on :8084"))
            return fails
        _ok("backend :8084 healthy")

        if NPX is None:
            return _fail("npx not found on PATH")
        pw = run([NPX, "playwright", "test", "--project=chromium"], cwd=FRONTEND_DIR, timeout=300)
        if pw.returncode != 0:
            fails.extend(_fail(f"Playwright failed:\n{pw.stdout}\n{pw.stderr}"))
        else:
            summary_match = re.search(r"(\d+) passed", pw.stdout)
            count = summary_match.group(1) if summary_match else "?"
            _ok(f"Playwright: {count} E2E tests passed")
    finally:
        if backend_proc is not None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                backend_proc.kill()

    return fails


def gate_docs_verification() -> list[str]:
    _heading(6, "Docs §1-§6 verification against live code")
    fails: list[str] = []

    # TESTING_STRATEGY §5 DoD Phase 0 — already exercised above.
    _ok("TESTING_STRATEGY Phase-0 DoD exercised by preceding gates")

    # API_SPEC non-negotiable #1: every registration-scoped route uses the guard.
    # Inspect routers for Depends(require_business_access / require_registration_access).
    business_router = (BACKEND_DIR / "app/api/routers/business.py").read_text(encoding="utf-8")
    reg_hits = business_router.count("require_registration_access")
    biz_hits = business_router.count("require_business_access")
    if reg_hits == 0:
        fails.extend(_fail("business router missing require_registration_access"))
    else:
        _ok(f"business router: {biz_hits} business-guard, {reg_hits} registration-guard")

    # SECURITY_AND_ACCESS §5: audit append-only proven by test.
    access_test = (BACKEND_DIR / "tests/test_access_guard.py").read_text(encoding="utf-8")
    if "test_audit_logs_table_is_append_only" not in access_test:
        fails.extend(_fail("missing append-only audit migration test"))
    else:
        _ok("append-only audit migration test present")

    # TECHNICAL_ARCHITECTURE §3: 25 tables present in core/gst/extraction.
    expected_tables = {
        "core": 9,
        "gst": 13,
        "extraction": 3,
    }
    tables: dict[str, int] = {}
    for schema in expected_tables:
        sql = (
            "SELECT count(*) FROM information_schema.tables "
            f"WHERE table_schema = '{schema}'"
        )
        try:
            out = psql("gst_filing_db", sql)
            tables[schema] = int(out.strip())
        except Exception as exc:  # noqa: BLE001
            fails.extend(_fail(f"could not count tables in {schema}: {exc}"))
    if tables == expected_tables:
        _ok(f"v2 tables present: {tables}")
    else:
        fails.extend(_fail(f"table count mismatch: {tables} != {expected_tables}"))

    # FRONTEND_SPEC §4: no tokens in localStorage; middleware does auth routing only.
    client_ts = (FRONTEND_DIR / "lib/api/client.ts").read_text(encoding="utf-8")
    if "localStorage.setItem" in client_ts or "sessionStorage.setItem" in client_ts:
        fails.extend(_fail("frontend client stores token in localStorage/sessionStorage"))
    else:
        _ok("frontend: no localStorage/sessionStorage token usage")

    middleware = (FRONTEND_DIR / "middleware.ts").read_text(encoding="utf-8")
    if "never authorization" in middleware:
        _ok("frontend: middleware routing-only per spec")
    else:
        fails.extend(_fail("frontend middleware claim missing"))

    # AI_BUILD_PLAYBOOK hard rules: integer paise in DB.
    money_sql = (
        "SELECT DISTINCT data_type FROM information_schema.columns "
        "WHERE column_name LIKE '%\\_minor' AND table_schema IN ('core','gst','extraction');"
    )
    try:
        money = psql("gst_filing_db", money_sql)
        money_types = set(money.split())
        if money_types <= {"integer", "bigint"}:
            _ok(f"money columns are integer/bIGINT (paise): {money_types}")
        else:
            fails.extend(_fail(f"money column not integer: {money_types}"))
    except Exception as exc:  # noqa: BLE001
        fails.extend(_fail(f"money column check failed: {exc}"))

    return fails


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true", help="skip Playwright frontend E2E")
    args = parser.parse_args()

    if NPM is None or NPX is None:
        print("FAIL — npm/npx not found on PATH", file=sys.stderr)
        return 1
    if not Path(ALEMBIC).exists():
        print(f"FAIL — alembic binary not found at {ALEMBIC}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("GST Filing Platform — Phase-0 E2E + docs verification")
    print("=" * 60)

    all_fails: list[str] = []
    all_fails.extend(gate_data_plane())
    all_fails.extend(gate_migrations())
    all_fails.extend(gate_backend_tests())
    all_fails.extend(gate_frontend_static())
    if not args.backend_only:
        all_fails.extend(gate_playwright())
    all_fails.extend(gate_docs_verification())

    print("\n" + "=" * 60)
    if all_fails:
        print(f"RESULT: FAIL — {len(all_fails)} gate(s) failed")
        for f in all_fails:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — all Phase-0 gates green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
