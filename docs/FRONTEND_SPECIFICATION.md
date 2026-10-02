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
│   │   ├── login/page.tsx            # email OTP / password login
│   │   └── register/page.tsx         # email signup
│   ├── (dashboard)/
│   │   ├── /                         # home: GSTIN switcher + per-GSTIN month cards + deadlines
│   │   ├── gst-accounts/             # GSTIN management (add GSTIN, collaborators)
│   │   ├── [gstin]/months/[fp]/      # month workspace (upload + ledger + review)
│   │   ├── [gstin]/returns/[fp]/     # GSTR-1/3B return prep, export history, amendments
│   │   ├── [gstin]/itc/[fp]/         # 2B import + reconciliation report
│   │   ├── review/[docId]/           # side-by-side extraction review
│   │   └── settings/                 # user profile, DPDP export/erasure
├── components/
│   ├── ui/                           # shadcn/ui primitives
│   ├── upload/                       # dropzone, photo-burst grouper, job status chips
│   ├── review/                       # ExtractedField, ConfidenceBadge, DocImagePane
│   ├── returns/                      # SectionTabs (B2B/B2CS/CDNR/...), ExportHistory
│   └── shared/                       # GstinSelector, DeadlineCountdown, StatusChip, GstinInput
├── lib/
│   ├── api/                          # typed client (generated from Pydantic schema)
│   ├── format/                       # paise→₹, Indian numbering, dates, fp labels
│   └── validation/                   # GSTIN checksum (mirror), PAN regex
└── middleware.ts                     # JWT auth check + session guard
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