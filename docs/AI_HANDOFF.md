# AI Handoff Guide — GST Filing App

**Repo:** `github.com/Sudarshan077/gst1` (branch `main`)
**Status:** ✅ Build complete — **48 / 48 tasks done** (see [BUILD_TRACKER.md](BUILD_TRACKER.md))
**Purpose of this doc:** the fastest path for a fresh AI agent (or human) to boot the app, exercise it, and know exactly what data is needed. Read this first; it points to everything else.

---

## 1. What this app is

A GST (Goods & Services Tax, India) return-filing platform. A user attaches a GSTIN, uploads purchase/sale invoices (PDF/photo), the app extracts line items, validates them, reconciles ITC, prepares **GSTR-1 / GSTR-3B** returns, and files them via a GSP/IRP adapter.

**Core product path (the one that matters):** *user uploads a file → gets return output (GSTR-1/3B) directly.*

- Backend: Python 3.11 · FastAPI · SQLAlchemy · Alembic · PostgreSQL · Redis · MinIO
- Frontend: Next.js 16 (App Router) · TypeScript · Tailwind · port **9094**
- Backend port **8084** · PG **5436** · Redis **6380** · MinIO **9001**
- Money is **integer paise** everywhere (never floats/rupees).

---

## 2. Boot the stack (copy-paste)

```bash
# 0. Infra — PostgreSQL:5436, Redis:6380, MinIO:9001 (idempotent; verify with --check)
cd /d/gst_filing_app
backend/.venv/Scripts/python.exe scripts/bootstrap_stack.py
backend/.venv/Scripts/python.exe scripts/bootstrap_stack.py --check   # expect 3x OK

# 1. Backend (background terminal; --factory is required)
cd /d/gst_filing_app/backend
./.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --port 8084 --host 127.0.0.1

# 2. Frontend
cd /d/gst_filing_app/frontend
npm run dev -- --port 9094

# 3. Health gates
curl -s http://127.0.0.1:8084/api/v1/health          # 200 (note: /health 404s — it is /api/v1/health)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9094/login   # 200
```

**Windows notes for the agent:**
- `terminal` runs **git-bash**, not PowerShell. Use POSIX syntax.
- `redis-cli` does not exist in this repo's `tools/` (only the server). The CLI lives at `/d/farmer_app/tools/redis/redis-cli.exe`.
- Kill a stray dev server by PID: `netstat -ano | grep ':9094'` then `taskkill -F -PID <n>` (the `-F -PID` dash form; slash forms misbehave in git-bash).
- A stale backend process serves OLD routes — **restart uvicorn after backend edits** (`--reload` is not used here).

---

## 3. Seed demo data (what data you need)

The app is empty on a fresh DB. Auth is **email-only OTP**; **dev mode echoes the OTP** in the API response, so no mail server is needed.

```bash
# seeds demo.tony@example.com + 4 checksum-valid GSTINs across schemes
backend/.venv/Scripts/python.exe scripts/seed_demo.py
```

**Login (manual or API):**
1. `POST /api/v1/auth/otp/request` `{identifier, purpose:"REGISTER"|"LOGIN"}` → `data.dev_otp`
2. `POST /api/v1/auth/otp/verify` `{identifier, otp}` → `data.access_token`
3. `POST /api/v1/gst-accounts` `{gstin, legal_name, filing_scheme}` per account

**Data rules you MUST follow:**
| Rule | Why |
|---|---|
| GSTINs must be **mod-36 checksum-valid** | hand-typed literals fail `422 invalid GSTIN checksum`. Generate with `make_gstin()` (see `scripts/seed_demo.py`). **Never invent a GSTIN.** |
| `filing_scheme` ∈ `REGULAR_MONTHLY` \| `QRMP` \| `COMPOSITION` | anything else → `422 VALIDATION_ERROR` |
| Identifiers are **email-only** (needs `@` and a dotted domain) | `validate_identifier` rejects phone-format |
| OTP is rate-limited **5/hour/identifier** | re-running a demo >5× looks broken. Clear it: `/d/farmer_app/tools/redis/redis-cli.exe -p 6380 del "otp_rl:demo.tony@example.com"` |
| Each demo upload fixture must be **byte-unique** | sha256 dedupe 409s a repeated identical file |
| Filing period `fp` must match `^(0[1-9]\|1[0-2])(20\d{2})$` | otherwise `422` (e.g. `092026` = Sep 2026) |

**Sample invoices** for upload: see [`test-samples/`](../test-samples/) — real sample PDFs + a corrupt file + a non-PDF, with a README explaining each.

---

## 4. See it work — three ways

### A. Guided tour with screenshots (recommended)
```bash
cd /d/gst_filing_app/frontend
NODE_PATH="D:/gst_filing_app/frontend/node_modules" node ../scripts/app_tour.cjs
```
Drives the real UI (login → shell → upload → review → confirm → returns download), prints one `[STEP]` line per screen, writes **screenshots + `tour-report.json`** into `docs/demo-screenshots/`.
> `NODE_PATH` is mandatory: node resolves modules from the *script's* dir, not the cwd.

### B. Playwright E2E (assertions)
```bash
cd /d/gst_filing_app/frontend
npx playwright test tests/task7-2-upload-to-output.spec.ts   # upload→output happy path
```
Self-boots the dev server via `playwright.config.ts` (`reuseExistingServer: true`). Backend :8084 must be up first.

### C. API-only probes
See [TESTING_GUIDE.md](TESTING_GUIDE.md) §4 for the curl/httpx recipe covering screens that are URL-only.

---

## 5. Feature inventory (what shipped)

**48/48 tasks across 8 phases.** Highlights by phase (full ledger in BUILD_TRACKER.md):

| Phase | Feature area |
|---|---|
| 0 | Skeleton, bootstrap stack, DB models (GSTIN-primary-key), email OTP auth + JWT refresh rotation + TOTP, GSTIN guard + audit, GST Accounts CRUD, unified web shell |
| 1 | Document upload + MinIO (GSTIN-scoped), extraction worker (preprocess→OCR→LLM→validator), review/confirm, access management, bulk CSV onboarding, dashboards, sandbox IRP adapter |
| 2 | GSTR-1 generator + self-validator + nil, CDNR/CDNUR, GSTR-3B build, GSTR-2B import + ITC reconciliation, GSTR-1A amendments, deadline engine, golden-set extraction gates |
| 3 | Multi-client CA roster, member permissions + audit UI, notifications (email/WhatsApp/in-app), DPDP export/erasure + retention, CMP-08/GSTR-4 composition |
| 4 | GSP adapter (live filing + 2B auto-fetch), live IRP adapter (gated), sandbox filing E2E |
| 5 | Production infra (self-hosted), free-tier GSP/IRP onboarding, security hardening + vuln scan, DPDP retention verification, UAT + full regression |
| 6 | 3-lens verification sweep of Phases 0–5 (code / frontend-user / GST-domain) |
| 7 | Single email-only user model, email-only auth end-to-end, **upload→output happy path** |

**Key API surfaces** (full list: `curl -s http://127.0.0.1:8084/openapi.json`):
- Auth: `otp/request`, `otp/verify`, `refresh`, `stepup`, `totp/*`, `login/password`, `me`
- Documents: upload/list (`gst-accounts/{gstin}/months/{fp}/documents`), `{doc_id}/draft` (GET/PUT), `extract` (dev), `confirm`, `reject`
- Returns: `gstr1/prepare|generate|export.json`, `gstr1a`, `gstr3b/export.json`, `gstr2b/import|fetch`, `itc/reconcile`, `month summary`, `filed`
- Compliance: `dpdp/export|erasure`, `me/data/export|erasure-request`, `audit`, `collaborators`, `notification-prefs`
- Filing: `gsp/gstr1/file`, `gsp/gstr3b/file`, `invoices/{id}/irn`, `einvoices/{irn}/cancel`

---

## 6. Known caveats (don't re-litigate these)

- **Test coverage vs floor:** full suite is **210 passed / 0 failed**, but total coverage is **~79.4 %** against an 80 % `--cov-fail-under`. This is **pre-existing at HEAD** (baseline 79.42 %); it is a coverage-floor gap, not a failing test. Run with `--no-cov` to isolate behaviour.
- **mypy:** 67 errors, **all in pre-existing test files** (`tests/`), 0 in `app/`. Identical at HEAD — not a regression.
- `build/plan.json` + `build/state.json` are **gitignored** (agent loop artifacts). The committed `docs/BUILD_TRACKER.md` is the authoritative progress record; `scripts/generate_tracker.py` needs those two files present to regenerate.
- Some screens are **URL-only** (returns exports, audit, collaborators, DPDP, e-invoice) — reachable directly, not always linked in the shell nav. Probe by API.
