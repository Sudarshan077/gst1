# Frontend Specification

> **Status:** v1.0 (2026-09-26) · Owner doc for the Next.js web app: structure, screens, states, design tokens
> **Stack:** TypeScript + Next.js (App Router) + Tailwind CSS + shadcn/ui · Port 9094
> **API contract:** API_SPECIFICATION.md · **Product journeys:** PRD.md §4

---

## 1. App structure

```
frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx                 # email-only OTP login (no mobile field)
│   │   ├── register/page.tsx              # email signup
│   │   └── totp/page.tsx                  # TOTP enrollment (QR + verify)
│   ├── (client)/app/                      # unified single-user shell (PHASE8 8.5)
│   │   ├── page.tsx                       # dashboard: GSTIN cards + filing-status grid
│   │   ├── profile/                       # own profile (name editable, email read-only) — PHASE8 8.6
│   │   ├── settings/                      # notification prefs, TOTP entry, sessions — PHASE8 8.7
│   │   ├── businesses/                    # list + add GSTIN — PHASE8 8.8
│   │   ├── businesses/[gstin]/            # detail + edit business fields — PHASE8 8.8
│   │   ├── upload/[gstin]/[fp]/           # month workspace (upload + ledger)
│   │   ├── review/[gstin]/[fp]/[docId]/   # side-by-side extraction review
│   │   ├── returns/[gstin]/[fp]/          # returns workspace (generate→format→validate→file) — PHASE8 8.9
│   │   ├── file/[gstin]/[fp]/             # GSP filing hub (additive, restored)
│   │   └── einvoice/[gstin]/[fp]/         # IRN board
│   ├── (ca)/ca/                           # CA roster view (additive, kept)
│   ├── layout.tsx
│   └── page.tsx                           # landing (redirects per auth state)
├── components/
│   ├── shared/ShellNav.tsx                # persistent nav: Dashboard·Businesses·Upload·Returns·Profile·Settings + GSTIN switcher
│   └── ui/                                # shadcn/ui primitives
├── lib/                                   # typed API client, session helpers
└── middleware.ts                          # auth guard (routing only — server is the authority)
```

## 2. Design tokens

| Token | Value | Use |
|---|---|---|
| `--accent` | Indigo-600 | primary actions, links |
| Deadline colors | green >7d · amber 3–7d · red <3d · slate FILED | DeadlineCountdown |
| Confidence colors | green ≥threshold · amber below · red invalid | ConfidenceBadge |
| Status chips | OPEN slate · NEEDS_REVIEW amber · CONFIRMED green · FILED blue · REVOKED red | StatusChip |
| Money | `₹1,23,456.78` (Indian grouping), paise ints from API — never floats | lib/format |

Typography: Inter; tables dense (13px), dashboards 14px. Dark mode: shadcn default tokens only — no custom theme forks.

## 3. Key screens & states

### 3.1 Month workspace `[gstin]/months/[fp]`

| State | Rendering |
|---|---|
| Empty month | Upload CTA card with capture-source hints (photo/scans) |
| Jobs running | Per-doc status chips (QUEUED→PREPROCESS→OCR→LLM→EXTRACTED); auto-poll, backoff |
| Needs review | Amber count in header → review queue sorted confidence-ascending |
| Confirmed ledger | Sales/Purchases toggle; sortable table; section chips (B2B/B2CL/B2CS/CDNR/EXP); totals card (taxable, CGST/SGST/IGST, RCM, ITC-books) |
| Nil month | Nil-return banner + one-click nil GSTR-1 |
| Filing week | DeadlineCountdown prominent; "X docs unreviewed" blocking warning on return prep |
| Batch upload | Multi-file picker/drop (≤10 files, 25 MB/file); local queue rows with per-file upload → extraction status (backend JobStatus values), per-row failure + retry; files post sequentially via the single-document API. ZIP expansion out of scope. Additive — the single-file card keeps its `file-input`/`upload-submit` contract |

### 3.2 Review screen `review/[docId]`

| Element | Behavior |
|---|---|
| Doc image pane | Original page image (presigned URL), zoom/pan |
| Extracted fields | Grouped (parties / invoice / tax); ConfidenceBadge per field; amber highlight below threshold; invalid GSTIN = red + locked to manual re-key |
| Edit → save | Re-runs client-side GSTIN checksum; PUT draft; validator re-runs server-side; confirm button enabled only when clean |
| Keyboard | Tab cycles amber fields first |

### 3.3 GSTIN Dashboard `/`

| Element | Behavior |
|---|---|
| Search | GSTIN prefix + trade-name substring; debounced |
| Grid | Per business: per-registration month chips (OPEN/READY/FILED + days-to-deadline), red flag if pending reviews within filing week |
| Add client | GSTIN request flow (A); invite-code redeem (B); bulk CSV import link |
| Row → detail | client detail with all registrations, active links, consent status |

### 3.4 Return prep `[gstin]/returns/[fp]`

| Step UI | Behavior |
|---|---|
| Guard | Blocks if pending reviews >0; shows which docs |
| Prepare | Dual-path banner (JSON vs IRN by `irn_applicable`); progress; self-validator result (errors block download) |
| Export | Download button → step-up OTP; export history table (schema_version, totals, generated_by, AMENDMENT badge) |
| Amendments | Post-filing corrections form → delta list → GSTR-1A export |

### 3.5 ITC `[gstin]/itc/[fp]`

2B upload → import progress → reconciliation table (5 status filters: MATCHED/PROBABLE/UNMATCHED/MISSING_IN_2B/MISSING_IN_BOOKS) → ITC summary prefill for 3B → "chase supplier" action list.

### 3.6 Profile `/app/profile` (PHASE8 8.6)

| Element | Behavior |
|---|---|
| Name | inline edit `full_name` → save → persists after reload |
| Email | shown read-only — no edit surface (server rejects `{email}` with 422) |
| States | save/error toasts; no password or mobile surface |

### 3.7 Settings `/app/settings` (PHASE8 8.7)

| Element | Behavior |
|---|---|
| Notification prefs | per-event channel toggles → save → persists after reload (via `PATCH /me/settings` → notification-prefs delegation) |
| Security | TOTP entry links to the enrollment flow and reflects enabled state |
| Session | active-session count; sign-out-everywhere revokes other devices' sessions |

### 3.8 Manage businesses `/app/businesses`, `/app/businesses/[gstin]` (PHASE8 8.8)

| Element | Behavior |
|---|---|
| List | all accessible GSTINs with role + scheme |
| Add GSTIN | client-side mod-36 checksum validation before submit (server re-validates); `filing_scheme` picker |
| Detail | editable `legal_name`, `trade_name`, `registered_address`, `filing_scheme`; this-FY per-period statuses via `GET …/overview` |

### 3.9 Returns workspace `/app/returns/[gstin]/[fp]` (PHASE8 8.9)

| Step UI | Behavior |
|---|---|
| Generate | one button → `POST …/returns/generate` (idempotent, prepares + generates GSTR-1 **and** 3B) → per-return status |
| Format picker | JSON **or** Excel (.xlsx, server-rendered) — existing `download-gstr1` / `download-gstr3b` testids preserved (7.2 spec depends on them) |
| HSN table | per-HSN summary; totals reconcile to GSTR-1 |
| Validation checklist | pre-file blocker/warning list from `GET …/returns/validation`; blocking entries must clear before file |
| Additive | prior JSON download buttons and history remain |

### 3.10 Dashboard filing-status tracker `/app` (PHASE8 8.10)

| Element | Behavior |
|---|---|
| Status grid | per-GSTIN × period roll-up: filed / draft / pending + quick actions |
| Additive | existing `gst-account-card` + `upload-link` testids and layout stay intact |

### 3.11 App shell nav (PHASE8 8.5)

Persistent `ShellNav.tsx`: **Dashboard · Businesses · Upload · Returns · Profile · Settings** + GSTIN switcher, active-route highlight. Every screen is reachable **by clicking the nav** from `/app` — enforced by `phase8-product-shell.spec.ts`.

## 4. Frontend rules (AI-builder constraints)

| Rule | Detail |
|---|---|
| Types | All API types generated from the backend Pydantic schema (`make api-types`); never hand-written duplicates |
| Money | paise integers end-to-end; conversion ONLY in `lib/format` |
| Errors | API errors render via one toast + inline pattern; no silent catches |
| Loading | Skeleton rows (shadcn) — no spinners over whole pages |
| Empty states | Every list/table has a designed empty state with next action |
| Access | All data via guarded API routes; middleware handles routing only, never authorization (server is the authority) |
| Forms | react-hook-form + zod (schemas mirror the API's Pydantic contracts) |
| GSTIN input | Client-side checksum for instant feedback; server always re-validates |

## 5. Acceptance (per screen)

| Screen | Done when |
|---|---|
| Login/register | Email OTP/password signup & login works |
| GSTIN Dashboard | Displays all accessible GSTINs, active periods, and deadlines |
| Month workspace | Photo-burst upload → job chips through pipeline → review → confirmed totals update live |
| Review | Amber fields editable, confirm blocked while dirty/invalid |
| Return prep | Guard blocks; JSON download only after validator passes; history immutable |
| ITC | 2B import → 5-status report → 3B prefill |
| DPDP | Self-service export downloads; erasure request flow completes |
| Profile (PHASE8) | edit name → save → persists; email read-only (Playwright-verified) |
| Settings (PHASE8) | toggle pref → save → persists; sign-out-everywhere revokes other session |
| Businesses (PHASE8) | add checksum-valid GSTIN → list → detail → edit legal_name → persists; corrupted GSTIN rejected client-side |
| Returns workspace (PHASE8) | generate → status → HSN table → validation checklist → Excel downloads |
| Dashboard tracker (PHASE8) | status grid renders filed/draft/pending per period for a seeded GSTIN |
| Shell nav (PHASE8) | every Phase-8 screen reachable by clicking nav from `/app` |