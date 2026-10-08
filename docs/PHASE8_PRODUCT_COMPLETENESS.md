# Phase 8 — Product Completeness: Profile, Settings, Business Management & Filing-Ready Returns

**Author:** Hermes (recon + web research) · **Requested by:** Tony · **Date:** 8 Oct 2026
**Repo:** `D:\gst_filing_app` · **Trigger:** the shipped app has no user-facing "account" layer (profile, settings, manage-business) and the returns flow produces a JSON download only — no generate step, no format choice, no pre-filing checks.

---

## 1. Gap analysis — what a GST filing product must have vs. what we shipped

Derived from the live tree + current practitioner expectations (see §6 sources). "Have" = verified present in this repo; "Missing" = the gap this phase closes.

| # | Standard capability | Status in repo | Evidence |
|---|---|---|---|
| 1 | **Profile** — view/edit own name; email read-only | ❌ Missing | no `/profile` route; `/auth/me` is read-only and has no edit surface |
| 2 | **Settings** — notification prefs, security (TOTP), session | ⚠️ API only | `GET/PATCH /me/notification-prefs` + `/auth/totp/*` exist; **no settings screen** |
| 3 | **Manage businesses** — add / edit / detail per GSTIN | ⚠️ API only | `PATCH /gst-accounts/{gstin}` exists; no edit UI |
| 4 | **Persistent app navigation** | ❌ Missing | `components/shared/ShellNav.tsx` = logo + role + user + Sign out. **Zero nav links** → returns/file/einvoice are orphaned |
| 5 | **Returns: generate step** | ⚠️ Partial | `POST …/gstr1/prepare` + `…/gstr1/generate` exist; the UI jumps straight to download |
| 6 | **Returns: format choice** (JSON **and** Excel/CSV) | ❌ Missing | `returns/page.tsx` downloads JSON only |
| 7 | **HSN summary** | ❌ Missing in UI | computed in the GSTR-1 payload, never surfaced |
| 8 | **Pre-filing validation ("error catcher")** | ⚠️ Partial | validator flags exist at extraction; no pre-file checklist on the returns screen |
| 9 | **Dashboard: filing-status tracker across GSTINs + periods** | ⚠️ Partial | `/app` lists GSTIN cards; no month/period filing status roll-up |
| 10 | **Audit trail UI** | ⚠️ API only | `GET /gst-accounts/{gstin}/audit`; no screen |
| 11 | **Collaborators / user access** | ⚠️ API only | `/collaborators` CRUD exists; no screen |
| 12 | **Contact master** (customers/vendors) | ❌ Missing | not modelled |
| 13 | **Password login** | ⚠️ Dormant | `POST /auth/login/password` + `password_hash` column exist; **no UI calls it**, no user has a password |

**Verdict:** the engine (extraction, returns math, filing adapters, auth, tenancy) is complete and verified. What is missing is the **account/product shell** — the screens and the last mile of the returns workflow. That is exactly what Phase 8 builds.

---

## 2. Scope decision

**In scope (Phase 8):** items 1–11 above. These are the "basic things a website has" Tony flagged, plus the returns generate/format/HSN/validation last mile.

**Explicitly out of scope (Phase 9 candidates):** 12 (contact master — needs a new model + migration) and 13 (password UI — contradicts the deliberate email-only decision of task 7.1B; reopen only on explicit instruction).

**Non-negotiable constraints carried from the existing build:**
- **Additive only.** Never remove or retire an existing screen. `/app/upload`, `/app/review`, `/app/file`, `/app/returns`, `/app/einvoice`, `/ca` stay exactly reachable.
- **Single user model** — no CA/business-owner role split (7.1A).
- **Email-only auth** — no mobile field anywhere (7.1B).
- **Free / OSS only** — no paid services; Excel/CSV export is generated **server-side in-process** (no paid spreadsheet library — use `openpyxl` which is OSS, or stdlib `csv` + a real `.xlsx` writer).
- **Money is integer paise** everywhere; never floats.
- **Never invent a GSTIN** — every fixture uses `make_gstin()`.
- Every task ends with the standard gates + its own test; the phase ends with an E2E.

---

## 3. Task plan (Phase 8)

Eleven tasks. Backend first (contracts), then the shell, then the workflow last mile, then the proof pass.

### 8.1 — Backend: User Profile API
| Field | Detail |
|---|---|
| Deliverable | `GET /api/v1/me/profile` + `PATCH /api/v1/me/profile` |
| Contract | `PATCH` accepts `{full_name}` only; `email` is **read-only** (attempt to patch it → 422, never silent-ignore). Returns the same `UserDto` shape as `/auth/me`. |
| Rules | Audit row on edit (`PROFILE_UPDATED`). No password/mobile surface. |
| done_when | pytest covers: read, patch name → 200 + persisted, patch email → 422; `/auth/me` still green; ruff + mypy clean on `app/`. |

### 8.2 — Backend: Settings API
| Field | Detail |
|---|---|
| Deliverable | `GET /api/v1/me/settings` (consolidated) returning notification prefs + TOTP status + session info |
| Contract | Read-only aggregate over existing `notification_preferences` + `totp_enabled_at`; PATCH delegates to the existing prefs handler (no duplicated write logic) |
| done_when | pytest: settings read returns prefs + `totp_enabled`; PATCH prefs round-trips through `/me/settings`; ruff/mypy clean. |

### 8.3 — Backend: Business (GSTIN) management completion
| Field | Detail |
|---|---|
| Deliverable | Extend `GET/PATCH /gst-accounts/{gstin}` with editable business fields (`legal_name`, `trade_name`, `registered_address`, `filing_scheme`) + `GET /gst-accounts/{gstin}/overview` (detail + this-FY filing status per period) |
| Rules | PATCH requires FILER/ADMIN; guard contract unchanged (`AccessDenied → 404 GSTIN_NOT_FOUND`, `PermissionDenied → 403`); audit on every write |
| done_when | pytest: patch legal_name → 200 + audit row; patch as VIEWER → 403; overview returns periods with statuses; ruff/mypy clean. |

### 8.4 — Backend: Returns generate pipeline + format export + HSN + pre-file validation
| Field | Detail |
|---|---|
| Deliverable | (a) `POST …/returns/generate` — idempotent orchestration of prepare→generate for GSTR-1 and 3B, returning a status envelope; (b) `GET …/gstr1/export.xlsx` + `…/gstr3b/export.xlsx` (**real .xlsx** via `openpyxl`, OSS); (c) `GET …/gstr1/hsn-summary`; (d) `GET …/returns/validation` — the pre-filing error-catcher (blocking vs warning) |
| Rules | Excel must carry the same numbers as the JSON (single source of truth — build one payload, render twice). Paise → rupees only at render. Validation re-uses the existing validator, never a parallel rule set. |
| done_when | pytest: generate returns per-return status; xlsx opens and cell values equal the JSON integers; hsn-summary totals reconcile to GSTR-1; validation returns `{blocking:[], warnings:[]}` on a clean period and a blocking entry when a filed-period conflict exists; ruff/mypy clean. |

### 8.5 — Frontend: App shell navigation (additive)
| Field | Detail |
|---|---|
| Deliverable | Persistent nav in `ShellNav.tsx`: **Dashboard · Businesses · Upload · Returns · Profile · Settings** + a GSTIN switcher; active-route highlight |
| Rules | Additive — the existing logo/user/Sign out stay. Every new route must be reachable **by clicking the nav**, not only by direct URL (this is the defect the sweep caught before). |
| done_when | `npx tsc --noEmit` + `npm run lint` clean; a nav-link grep shows every Phase-8 route referenced from the shell; existing Playwright specs still pass. |

### 8.6 — Frontend: Profile screen
| Field | Detail |
|---|---|
| Deliverable | `/app/profile` — view + inline edit of `full_name`; email shown read-only; save/error states |
| done_when | tsc+lint clean; Playwright: open via nav → edit name → save → value persists after reload. |

### 8.7 — Frontend: Settings screen
| Field | Detail |
|---|---|
| Deliverable | `/app/settings` — notification preferences, TOTP enable/disable entry, sign-out-everywhere (session), account summary |
| done_when | tsc+lint clean; Playwright: toggle a notification pref → save → persists. |

### 8.8 — Frontend: Manage businesses
| Field | Detail |
|---|---|
| Deliverable | `/app/businesses` (list + add GSTIN) and `/app/businesses/[gstin]` (detail + edit business fields) |
| Rules | Add-GSTIN form validates checksum **client-side too** with the same mod-36 rule; server remains authoritative |
| done_when | tsc+lint clean; Playwright: add a generated GSTIN → appears in list → open detail → edit legal_name → persists. |

### 8.9 — Frontend: Returns workspace (generate → format → validate → file)
| Field | Detail |
|---|---|
| Deliverable | Rework `/app/returns/[gstin]/[fp]` **additively** into: Generate button (calls 8.4) · format picker (JSON / Excel) · HSN summary table · pre-filing validation checklist · keep the existing JSON download buttons |
| Rules | Existing `download-gstr1` / `download-gstr3b` testids must survive (the 7.2 spec depends on them) |
| done_when | tsc+lint clean; existing 7.2 spec still passes; new Playwright: generate → Excel downloads → validation checklist renders. |

### 8.10 — Frontend: Dashboard filing-status tracker
| Field | Detail |
|---|---|
| Deliverable | Extend `/app` with a per-GSTIN × period filing-status roll-up (filed / draft / pending) and quick actions |
| Rules | Additive — the existing `gst-account-card` + `upload-link` testids and layout stay intact |
| done_when | tsc+lint clean; existing specs pass; new Playwright asserts the status grid renders for a seeded GSTIN. |

### 8.11 — Phase-8 E2E + full regression
| Field | Detail |
|---|---|
| Deliverable | `scripts/e2e_phase8.py` (3-lens harness) + `frontend/tests/phase8-product-shell.spec.ts`; re-run of the **whole** suite |
| done_when | Full pytest green, ruff/mypy clean, tsc/lint clean, ALL Playwright specs pass (7.2 + auth-onboarding + phase4 + phase8); a fresh AI can reach every Phase-8 screen by clicking nav from `/app`. |

---

## 4. Verification protocol (definition of done per task)

| Gate | Command | Must be |
|---|---|---|
| Backend tests | `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q --no-cov` | all pass |
| Lint | `./.venv/Scripts/python.exe -m ruff check .` | clean |
| Types | `./.venv/Scripts/python.exe -m mypy .` | no NEW errors in `app/` |
| Frontend types | `cd frontend && npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| E2E | `npx playwright test` | pass |
| Reachability (8.5+) | grep the shell for a `Link href` to each new route | every route linked |

---

## 5. Agent assignment (evidence-based)

From the **empirical scorecard** measured over a full build day (`references/ollama-cloud-models.md` § Empirical scorecard: wins vs STUCK kills, median win runtime) — not from model labels:

| Role | Primary | Failover | Rationale |
|---|---|---|---|
| **Builder** | `glm-5.3` | `kimi-k3` → `kimi-k2.7-code` | **0 % stuck, 54 wins, 63 s median.** `kimi-k2.7-code` carried the 'coding-specialised' label but had a **10.3 % stuck rate and a 411 s median** — it burned hours and was repeatedly stuck-killed. The model that *completes* wins over the model with the fancier label. |
| **Tester** | `glm-5.3-flash` | `minimax-m2.7` → `glm-5.3` | cheapest fast tier; 5.9 % stuck, 230 s median; minimax completed a full verdict when flash stuck |
| **Monitor** | `deepseek-v4.1-flash` | `minimax-m2.7` | **3.1 % stuck (1 kill in 32 runs — the most reliable rung on the account)** and deliberately **off the Tester's primary route**, so the pass/fail judgement never comes from the same upstream that produced the evidence |
| **Feedback** | `glm-5.3` | `kimi-k2.7-code` | same role as Builder |

This **re-ranks** the currently-committed chains (which still lead Builder/Feedback with `kimi-k2.7-code`, chosen before the scorecard existed). The harness edit must be **committed** or the loop's own rule-8 revert will silently drift it back.

---

## 6. Sources (feature expectations)

- GSTN offline-tool / JSON-upload filing flow (prepare offline → upload `returns.json` → file with DSC/EVC): patronaccounting.com e-filing guide; Razorpay offline-tools guide; TaxSlabs GSTR-1 prep tool.
- Filing-ready pack expectations (JSON **+** multi-sheet Excel, HSN summary, 2B reconciliation, error catcher): lekha.pro GST return filing software; Octa GST feature list.
- Account/product shell expectations (My Profile, Business Setting, User Access, Contact Master, Form Settings, reports, audit trail): ClearTax GST 2.0 Global/Local Settings docs; Zoho Books GST feature list.

---

## 7. Build execution

Phase 8 tasks are appended to `build/plan.json` and their slots to `build/state.json`, the harness chains are re-ranked and committed, then the 3-agent loop is relaunched (background, `persist_on_release=true`) with the watchdog cron polling. Each task is Builder→Tester→Monitor per §4; a defect found becomes a monitor RETRY with a concrete BUILDER_INSTRUCTION, never a silent hand-patch.
