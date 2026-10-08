# Testing Guide — GST Filing App

Everything a tester (human or AI) needs: the quality gates, the test inventory, the E2E recipes, and the API-only probes for screens that have no nav link.

**Backend venv:** `backend/.venv/Scripts/python.exe` (`mvnw` is Windows-only; unrelated — this is Python/Node).
**Prereqs:** infra up (`scripts/bootstrap_stack.py`), and for E2E a running backend on :8084.

---

## 1. Quality gates (the definition of done)

Run from the repo root unless noted.

```bash
# --- Backend ---
cd backend
./.venv/Scripts/python.exe -m pytest tests/ -q              # behaviour + coverage floor
./.venv/Scripts/python.exe -m pytest tests/ -q --no-cov     # behaviour only (210 tests)
./.venv/Scripts/python.exe -m ruff check .                  # lint
./.venv/Scripts/python.exe -m mypy .                        # types

# --- Frontend ---
cd frontend
npx tsc --noEmit                                            # types
npm run lint                                                # lint

# --- E2E ---
npx playwright test tests/task7-2-upload-to-output.spec.ts  # upload→output happy path
```

### Expected results (as of the last full run)
| Gate | Result | Note |
|---|---|---|
| `pytest tests/ -q --no-cov` | **210 passed, 0 failed** | junit-verified |
| `pytest tests/ -q` | 210 passed but **FAIL: coverage 79.4 % < 80 %** | pre-existing floor gap at HEAD (79.42 %); not a test failure |
| `ruff check .` | clean | |
| `mypy .` | 67 errors, **all in `tests/`** | identical at HEAD; 0 in `app/` |
| `npx tsc --noEmit` | clean (exit 0) | |
| `npm run lint` | clean (exit 0) | |
| `npx playwright test task7-2…` | **1 passed** | needs backend :8084 up |

> To get an unambiguous pass count when the pytest summary line vanishes, add `--junitxml=<absolute native path>` and parse the `testsuite` attributes. MSYS `$TMPDIR` is invisible to native python — use a `C:/...` path.

---

## 2. Test inventory

### Backend — `backend/tests/` (36 test modules, 210 tests)
| Area | Modules |
|---|---|
| Auth | `test_auth_otp`, `test_auth_password`, `test_auth_refresh`, `test_auth_totp`, `test_auth_me` |
| Access & tenancy | `test_access_guard`, `test_critical_gstin` |
| GST accounts & models | `test_gst_accounts`, `test_db_models`, `test_migrations`, `test_skeleton` |
| Documents & review | `test_documents`, `test_review_flow`, `test_review_service` |
| Extraction | `test_extraction_pipeline`, `test_extraction_preprocess`, `test_extraction_validator`, `test_extraction_worker` |
| Returns | `test_gstr1`, `test_gstr1a`, `test_gstr2b_itc`, `test_returns`, `test_returns_services` |
| Filing (GSP/IRP) | `test_gsp`, `test_gsp_irp_onboarding`, `test_irp_live_gated`, `test_einvoice` |
| Compliance | `test_dpdp`, `test_notification_prefs`, `test_notifications`, `test_notifications_router` |
| Deadlines | `test_deadline`, `test_critical_deadline` |
| Phase E2E | `test_e2e_phase2`, `test_e2e_phase3` |
| UAT | `test_uat_closed_beta` |

**Helpers (not tests):** `conftest.py`, `auth_helpers.py`, `v4_helpers.py`, `gstin_fixtures.py`. The **shared seed helper is `tests/v4_helpers.py`** — one stale generator there turns the whole tree red, so fix generators there, never per-module.

### Frontend — `frontend/tests/`
| Spec | Covers |
|---|---|
| `auth-onboarding.spec.ts` | email login → shell onboarding |
| `phase4-filing.spec.ts` | sandbox GSP filing flow |
| `task7-2-upload-to-output.spec.ts` | **upload → extract → review → confirm → GSTR-1/3B download** |
| `totp-utils.ts` | TOTP test helper |

---

## 3. E2E: upload-to-output (the core product path)

```bash
# backend up first (background, persist_on_release=true)
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --port 8084 --host 127.0.0.1

cd ../frontend && npx playwright test tests/task7-2-upload-to-output.spec.ts
```
The spec registers a throwaway user, creates a GSTIN, drives the UI, triggers dev-mode extraction, confirms, and downloads both returns. It self-boots the dev server (`reuseExistingServer: true`).

### Guided tour (screenshots for a demo)
```bash
cd frontend
NODE_PATH="D:/gst_filing_app/frontend/node_modules" node ../scripts/app_tour.cjs
```
Output → `docs/demo-screenshots/` (PNGs + `tour-report.json`); one `[STEP]` line per verified screen.

### Diagnosing an E2E failure
Trace the network + console (a full-load `goto` drops the in-memory bearer token, so an early `401` then a retry `200` is normal):
```js
page.on("response", r => { if (r.url().includes("/api/v1")) console.log("RESP:", r.status(), r.url()); });
```
Fingerprints seen in this repo:
- `{doc_id}/draft` → **500 `MultipleResultsFound`**: duplicate `invoice_drafts` rows for one job (re-extraction inserted a 2nd row). Fixed by upserting one draft per job in `app/extraction/worker.py`.
- `{doc_id}/confirm` → **401** after a successful draft load: concurrent 401s each called `refreshTokens()` directly, replaying the rotated cookie → `REFRESH_REUSE_DETECTED`. Fixed by routing the retry through the deduplicated `silentRefresh()` in `frontend/lib/api/client.ts`.
- Confirm button `disabled`: only `severity == "BLOCK"` flags should lock it (non-blocking `FLAG`/`SUGGEST`/`AUTO_CORRECT` must not).

---

## 4. API-only probes (features with no screen)

Seeded token required (`scripts/seed_demo.py`). `$T` = access token, `$G` = a GSTIN, `FP=092026`.

```bash
# health
curl -s http://127.0.0.1:8084/api/v1/health

# month summary (invoices + totals)
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/months/$FP/summary"

# returns exports (JSON downloads)
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/months/$FP/gstr1/export.json"
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/months/$FP/gstr3b/export.json"

# review queue, audit, collaborators, notifications, DPDP
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/months/$FP/review-queue"
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/audit"
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/gst-accounts/$G/collaborators"
curl -s -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/notifications"
curl -s -X POST -H "Authorization: Bearer $T" "http://127.0.0.1:8084/api/v1/me/data/export"   # DPDP; step-up may 403 STEP_UP_REQUIRED
```

**Expected error codes (these are correct behaviour, not bugs):**
| Probe | Expected |
|---|---|
| `POST /me/data/export` with no step-up | `403 STEP_UP_REQUIRED` |
| Upload into a FILED period | `423 PERIOD_LOCKED` |
| Duplicate invoice_no on confirm | `409 DUPLICATE_INVOICE` |
| Second confirm of same doc | `409 ALREADY_CONFIRMED` |
| Invalid GSTIN checksum | `422` with `invalid GSTIN checksum` |
| Bad `fp` (e.g. `132026`) | `422` (path pattern) |
| Phone-format identifier | `422 IDENTIFIER_INVALID` |

---

## 5. GST-domain checks (Lens 3)

For anything touching GSTINs or money:
1. **Checksum:** every GSTIN literal must pass mod-36. Cross-check with `python-stdnum`'s Luhn mod-36 (`luhn.calc_check_digit(first14, alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')`, weights 1-2-1-2…); a stricter `stdnum.in_.gstin.is_valid` also checks the PAN's 4th-char holder type, so a `False` there on a synthetic fixture does **not** mean the checksum failed. Prefer `app.core.gstin.make_gstin()` for every new fixture.
2. **Paise:** all money columns are integer paise; never compare a paise column to a rupee constant.
3. **Schema contract:** `docs/TECHNICAL_ARCHITECTURE.md` §3 is the governing table-shape contract (some task briefs name stale docs — verify the doc exists before asserting against it).
4. **Guard contract:** `AccessDenied → 404 GSTIN_NOT_FOUND` (existence never leaks); `PermissionDenied → 403`; audit is append-only keyed by gstin.
