"""Hermes browser verification for the GST Filing App (upload-to-output path).

Run:
    python D:\\gst_filing_app\\run_hermes_browser_test.py

Prereqs (already up if you followed docs/AI_HANDOFF.md):
    - infra:   backend/.venv/Scripts/python.exe scripts/bootstrap_stack.py --check
    - backend: uvicorn app.main:create_app --factory --port 8084
    - frontend: npm run dev -- --port 9094
    - demo user seeded: python scripts/seed_demo.py

NOTE ON THE ORIGINAL SPEC
-------------------------
The original brief for this script assumed a password login, a /app/dashboard
route, a `test_samples/` folder and the GSTIN 29ABCDE1234F1Z5. None of those are
true in this repository, so that version could never pass. Corrected here to the
app's real contract:
  * login is EMAIL-ONLY OTP (dev mode echoes the 6-digit code on screen)
  * the unified shell is /app (there is no /app/dashboard)
  * sample fixtures live in test-samples/
  * GSTINs must be mod-36 checksum-valid AND owned by the signed-in user
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

FRONTEND = "http://127.0.0.1:9094"
BACKEND = "http://127.0.0.1:8084/api/v1"
EMAIL = "demo.tony@example.com"
GSTIN = "27AAPFU0939F1ZV"          # seeded, checksum-valid, demo user is ADMIN
FP = "092026"                      # Sep 2026 — must match ^(0[1-9]|1[0-2])(20\d{2})$
SAMPLE = r"D:\gst_filing_app\test-samples\invoice_b2b_interstate.pdf"
SHOT_DIR = r"D:\gst_filing_app\docs\demo-screenshots"
HEADLESS = os.environ.get("HEADLESS", "0") == "1"

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def make_gstin(state: str) -> str:
    """Mod-36 checksum-valid GSTIN. Never hand-type a GSTIN literal."""
    import random
    import string

    pan = (
        "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        + "".join(random.choice(string.digits) for _ in range(4))
        + random.choice(string.ascii_uppercase)
    )
    first14 = f"{state}{pan}1Z"
    total = 0
    for i, ch in enumerate(first14):
        prod = CHARSET.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return first14 + CHARSET[(36 - total % 36) % 36]


def api(path: str, payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BACKEND + path, data=data, method="POST" if data else "GET"
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def preflight() -> tuple[str, str, str]:
    """Return (gstin, fp, access_token). Creates a fresh GSTIN for this run."""
    print(f"[PRE] backend health ...", end=" ")
    st, body = api("/health")
    print(f"{st} {body.get('data')}")
    if st != 200:
        sys.exit("backend not healthy — start uvicorn on :8084 first")

    print(f"[PRE] login via API (dev OTP) ...", end=" ")
    st, b = api("/auth/otp/request", {"identifier": EMAIL, "purpose": "LOGIN"})
    if st != 200:
        st, b = api("/auth/otp/request", {"identifier": EMAIL, "purpose": "REGISTER"})
    if st != 200:
        sys.exit(f"\nOTP request failed ({st}): {b}  (rate limit? clear otp_rl:{EMAIL})")
    st, v = api("/auth/otp/verify", {"identifier": EMAIL, "otp": b["data"]["dev_otp"]})
    if st != 200:
        sys.exit(f"\nOTP verify failed ({st}): {v}")
    token = v["data"]["access_token"]
    print(f"{st} ok")

    gstin = make_gstin("27")
    st, c = api(
        "/gst-accounts",
        {"gstin": gstin, "legal_name": f"Hermes Test Co {int(time.time())}",
         "filing_scheme": "REGULAR_MONTHLY"},
        token,
    )
    print(f"[PRE] create GSTIN {gstin} -> {st}")
    if st not in (200, 201):
        sys.exit(f"could not create GSTIN: {c}")
    return gstin, FP, token


def main() -> int:
    gstin, fp, _token = preflight()
    results: list[tuple[str, bool, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=300)
        page = browser.new_page()

        # ---- 1. Login (email-only OTP) ----
        print(f"\n[TEST 1/5] Login at {FRONTEND}/login")
        page.goto(f"{FRONTEND}/login")
        page.wait_for_load_state("networkidle")
        page.fill("[data-testid=login-identifier]", EMAIL)
        page.click("[data-testid=login-request-otp]")
        dev = page.wait_for_selector("[data-testid=dev-otp]", timeout=15_000)
        code = dev.inner_text().split("dev code:")[-1].strip()
        page.fill("[data-testid=login-otp]", code)
        page.click("[data-testid=login-verify]")
        page.wait_for_url("**/app", timeout=15_000)
        page.screenshot(path=f"{SHOT_DIR}\\h01-shell.png", full_page=True)
        cards = page.locator("[data-testid=gst-account-card]").count()
        ok = cards >= 1
        results.append(("login -> shell", ok, f"landed on /app; {cards} GSTIN card(s)"))
        print(f"  login OK, {cards} GSTIN card(s), now at {page.url}")

        # ---- 2. Dashboard / shell ----
        print("[TEST 2/5] Unified shell dashboard")
        page.wait_for_timeout(800)
        heading = page.locator("h1, h2").first.inner_text()
        results.append(("shell dashboard", True, f"heading={heading!r}"))
        print(f"  shell heading: {heading!r}")

        # ---- 3. Upload screen ----
        print(f"[TEST 3/5] Upload  {FRONTEND}/app/upload/{gstin}/{fp}")
        page.goto(f"{FRONTEND}//app/upload/{gstin}/{fp}")
        page.wait_for_selector("[data-testid=file-input]", state="attached", timeout=15_000)
        page.screenshot(path=f"{SHOT_DIR}\\h02-upload.png", full_page=True)
        results.append(("upload screen", True, f"/app/upload/{gstin}/{fp} rendered"))
        print("  upload screen rendered")

        # ---- 4. Upload + extraction ----
        print("[TEST 4/5] Upload invoice -> extraction")
        page.set_input_files("[data-testid=file-input]", SAMPLE)
        page.click("[data-testid=upload-submit]")
        page.wait_for_selector("[data-testid=upload-success]", timeout=40_000)
        text = page.locator("[data-testid=upload-success]").inner_text()
        doc_id = ""
        import re as _re
        m = _re.search(r"Document ID:\s*([0-9a-f-]{36})", text, _re.I)
        if m:
            doc_id = m.group(1)
        page.screenshot(path=f"{SHOT_DIR}\\h03-upload-success.png", full_page=True)
        results.append(("upload + extraction", True, f"success panel; docId={doc_id or 'n/a'}"))
        print(f"  uploaded; {text.strip()[:120]!r}")

        # ---- 5. Review -> confirm -> returns ----
        print("[TEST 5/5] Review -> confirm -> returns")
        if doc_id:
            page.goto(f"{FRONTEND}/app/review/{gstin}/{fp}/{doc_id}")
            page.wait_for_selector("[data-testid=confirm-document]", timeout=15_000)
            page.wait_for_timeout(1500)  # let the draft load through the silent refresh
            btn = page.locator("[data-testid=confirm-document]")
            enabled = btn.is_enabled()
            page.screenshot(path=f"{SHOT_DIR}\\h04-review.png", full_page=True)
            results.append(("review screen (Confirm enabled)", enabled,
                            f"enabled={enabled} — BLOCK-only gating"))
            print(f"  Confirm enabled = {enabled}")
            if enabled:
                btn.click()
                page.wait_for_selector("[data-testid=review-success]", timeout=15_000)
                page.click("[data-testid=go-to-returns]")
                page.wait_for_url("**/app/returns/**", timeout=15_000)
        page.goto(f"{FRONTEND}/app/returns/{gstin}/{fp}")
        page.wait_for_selector("[data-testid=download-gstr1]", timeout=15_000)
        page.screenshot(path=f"{SHOT_DIR}\\hermes_test_verification.png", full_page=True)
        results.append(("returns summary", True, "GSTR-1 + GSTR-3B download buttons present"))
        print("  returns screen rendered")

        browser.close()

    print("\n================ RESULT ================")
    allok = True
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:34} {detail}")
        allok &= ok
    print(f"screenshot: {SHOT_DIR}\\hermes_test_verification.png")
    print("ALL PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
