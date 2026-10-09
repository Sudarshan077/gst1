# Phase 9 — QA Sweep Fixes: Review UX, Extraction Feedback, Empty States, Batch Upload & ITC Visibility

**Author:** Hermes (verification-first) · **Requested by:** Tony · **Date:** 9 Oct 2026
**Repo:** `D:\gst_filing_app` · **Trigger:** external QA report with 6 findings; each was verified against live code before planning — verdicts below. **Additive only** (Phase-8 rule carried forward: never retire a shipped screen or testid).

---

## 1. Claim verification (done before any code changed)

| # | QA claim | Verdict | Evidence |
|---|---|---|---|
| A | Review screen: only `invoice_no` + `total_value_paise` editable → user trapped on OCR misreads | ✅ True (P0) | `review/[gstin]/[fp]/[docId]/page.tsx` "Quick edit (demo)" block — all other fields display-only |
| B | No extraction-status feedback; user can click "Review/confirm" while OCR still running | ✅ True (P0) | `upload/page.tsx` fetches job status once, no polling; success card navigates regardless of QUEUED state. `file/[gstin]/[fp]` queue also loads once, never refreshes |
| C | Single-file upload only | ✅ True (P1) | `files[0]` on drop, no `multiple` attribute, single `File` state |
| D | Any flag blocks confirmation | ❌ **False positive** | `services/review.py` `confirm_draft` filters `severity == "BLOCK"` only — the recommended behaviour already exists. Report hedges "early versions". Real (narrower) gap: `validate.py` currently emits only BLOCK severities; advisory rules should be WARN-tier |
| E | Dashboard empty state: text only, no CTA | ✅ True (P1) | `app/page.tsx` dashed box, no button |
| F | No ITC reconciliation UI | ✅ True (P2) | zero ITC/2B routes in `frontend/app`; zero reconcile calls in `lib/api/client.ts`; backend `itc/reconcile` + 2B import exist with no screen |

**Scope decision:** fix A, B, C, E, F as build tasks. D is closed as *verified-no-fix* on the confirm path; a narrow follow-up adds WARN-tier advisory rules where GST practice allows non-blocking flags — that is 9.6 (optional, tester decides if it lands this phase).

---

## 2. Non-negotiable constraints (carried from Phase 8)

- **Additive only** — existing screens, testids (`download-gstr1/3b`, `upload-submit`, `file-input`, `confirm-document`, `gst-account-card`, `upload-link`, …), and Playwright contracts stay intact.
- **Email-only auth, single user model** — no role split, no mobile fields.
- **Free/OSS only**; money is **integer paise** everywhere.
- **Never invent a GSTIN** — all fixtures via `make_gstin()`.
- Backend and frontend land **together** per task, one commit.

---

## 3. Task plan (Phase 9)

### 9.1 — Frontend: full-field review editor (P0)
| Field | Detail |
|---|---|
| Deliverable | Rework the review page "Quick edit" section into a full editor covering ALL editable draft fields: `invoice_no`, `invoice_date`, `buyer_gstin`, `supplier_gstin`, `place_of_supply`, `is_inter_state`, `rchrg`, `taxable_value_paise`, `cgst_paise`, `sgst_paise`, `igst_paise`, `cess_paise`, `total_value_paise` |
| Rules | Field-by-field save via existing `updateDraft` (PUT draft) — keep the `onBlur` save pattern. Client-side mod-36 checksum on GSTIN fields before submit (server re-validates). Paise inputs are integers. **Keep** the existing two quick-edit inputs' behaviour (additive rework, no testid removal). Flags panel stays visible; confirm stays disabled while BLOCK flags exist |
| done_when | tsc + lint clean; existing Playwright review specs pass; new spec: edit `buyer_gstin` (valid checksum) → save → value persists after reload; edit to a corrupted GSTIN → client rejects before network. Backend unchanged (PUT draft already accepts the full field set) |

### 9.2 — Frontend: extraction progress polling on upload (P0)
| Field | Detail |
|---|---|
| Deliverable | Upload success card polls `getDocument(id)` on an interval (2s, stop on terminal status EXTRACTED/NEEDS_REVIEW/FAILED/CONFIRMED, cap 5 min) and renders the live status label: `QUEUED → PREPROCESSING → OCR_RUNNING → LLM_EXTRACTING → EXTRACTED` with a spinner row. The "Review / confirm →" button stays but is **disabled** with a hint until the draft is ready (EXTRACTED/NEEDS_REVIEW) |
| Rules | Single active poller per docId; cleanup on unmount; no new backend endpoints. Documents queue page (`file/[gstin]/[fp]`) additionally gains a 5s re-list interval while any row is non-terminal, same terminal-stop rule |
| done_when | tsc + lint clean; new Playwright spec: upload → status chips appear and transition (stub the API or use dev-OTP seeded doc); button disabled while QUEUED, enabled on EXTRACTED. Existing upload-to-output spec (7.2) must still pass end-to-end |

### 9.2B — Frontend: batch upload queue (P1)  *(was QA item C)*
| Field | Detail |
|---|--- |
| Deliverable | Upload page supports **multi-file selection** (`multiple` + `files` array on drop): local queue table showing per-file upload → extraction status; each file posts `uploadDocument` + `triggerExtraction` sequentially (small batch ≤10 files; 25 MB/file cap unchanged); failures shown per-row with retry. Single-file path continues to work identically |
| Rules | ZIP-archive expansion is **out of scope** (backend single-doc API unchanged); additive — the `file-input` and `upload-submit` testids and their single-file contracts stay |
| done_when | tsc + lint clean; new spec: drop 2 files → both rows appear → both reach a terminal status; single-file spec unchanged |

### 9.3 — Frontend: dashboard empty-state CTA (P1)
| Field | Detail |
|---|---|
| Deliverable | Dashboard "No GST accounts linked yet" dashed box gains a primary **"+ Link or Register GSTIN"** button linking to `/app/businesses` (the Phase-8 add-GSTIN flow lives there) |
| Rules | Additive — the existing text and `gst-account-card`/`upload-link` testids stay; no new backend |
| done_when | tsc + lint clean; new spec: fresh user with 0 GSTINs sees the CTA; clicking navigates to `/app/businesses` |

### 9.4 — Frontend: ITC reconciliation dashboard (P2)
| Field | Detail |
|---|---|
| Deliverable | New screen `/app/itc/[gstin]/[fp]` + nav reachability from the returns workspace: 2B import status → books vs 2B side-by-side table with match-status badges (MATCHED/PROBABLE/UNMATCHED/MISSING_IN_2B/MISSING_IN_BOOKS), filterable by status, ITC summary prefill card for 3B, "chase supplier" action list for MISSING_IN_2B rows |
| Rules | Uses existing backend endpoints only (`itc/reconcile`, `gstr2b/import|fetch`, month summary); additive new route; add `itc` to the reachability audit so the shell nav links it (Phase-8 8.5 audit pattern) |
| done_when | tsc + lint clean; new spec: seeded period → reconcile → badges render per status; nav-click reaches the screen from `/app` |

### 9.5 — Backend: WARN-tier advisory validation rules (narrow D follow-up)
| Field | Detail |
|---|---|
| Deliverable | Audit `extraction/validate.py` for rules that GST practice treats as advisory and emit them as `severity: "WARN"` instead of BLOCK, plus add the missing obvious advisory rules: (a) invoice date older than 30 days before period end; (b) HSN shorter than 6 digits. Confirm path unchanged (already BLOCK-only). Review page renders WARN flags in the amber panel with "advisory" wording (no confirm blocking) |
| Rules | Zero behaviour change to BLOCK rules; confirm_draft untouched; validator tests extended for the new WARN rules; review.py confirm already filters BLOCK only |
| done_when | pytest: new WARN rules fire and do NOT block confirm (confirm with WARN-only flags → 200); existing validator tests pass; ruff/mypy clean |

### 9.6 — Phase-9 E2E + full regression
| Field | Phase-8 8.11 pattern |
|---|---|
| Deliverable | Extend `scripts/e2e_phase8.py` pattern → `scripts/e2e_phase9.py` (3-lens: full pytest, ruff/mypy, tsc/lint/playwright, GST-domain modules incl. new review/itc coverage) + `frontend/tests/phase9-*.spec.ts` for 9.1–9.4; reachability audit updated (itc route) |
| done_when | All lenses green in one run; 59+6 = 65/65 or the landed count in the regenerated tracker |

---

## 4. Verification protocol — unchanged (per task)

| Gate | Command | Must be |
|---|---|---|
| Backend tests | `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q --no-cov` | all pass |
| Lint | `./.venv/Scripts/python.exe -m ruff check .` | clean |
| Types | `./.venv/Scripts/python.exe -m mypy app/` | clean |
| Frontend types | `cd frontend && npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| E2E | `npx playwright test` (1 worker) | pass |

## 5. Agent assignment (unchanged from Phase-8 scorecard — ollama-cloud, NOT OmniRoute)

| Role | Model | Rationale |
|---|---|---|
| Builder | `glm-5.3` | 0% stuck, 54 wins, 63s median |
| Tester | `glm-5.3-flash` | cheapest fast tier |
| Monitor | `deepseek-v4.1-flash` | most reliable rung; off the Tester's route |
| Feedback | `glm-5.3` | same as Builder |

OmniRoute is intentionally shut down (Tony, 6 Oct) — the GST build runs ollama-cloud direct.