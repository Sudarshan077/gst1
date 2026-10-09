# Phase 10: Bug Sweep — FY Month Rollover, Shell Nav, Coverage Gate, Checksum Hint

Tony, 9 Oct 2026. Fixes the 4 confirmed functional/code bugs from the external review,
verified against the live tree before tasking. Additive only; no shipped screen or testid is removed.

## Verified findings

| # | Bug | Verified location | Severity |
|---|---|---|---|
| 10.1 | FY grid emits non-existent months `13/14/15 2026` (`132026`/`142026`/`152026`) | `backend/app/core/gst_accounts/service.py:424` `[f"{m:02d}{fy_start_year}" for m in range(4,16)]` | High |
| 10.2 | Workspace routes render no ShellNav (header/GSTIN switcher/user/nav missing) | `upload/[gstin]/[fp]`, `returns/[gstin]/[fp]`, `review/[gstin]/[fp]/[docId]`, `einvoice/[gstin]/[fp]`, `file/[gstin]/[fp]` — no shared client layout; ShellNav embedded per-page only in dashboard/profile/settings/businesses/itc | High UX |
| 10.3 | Coverage gate fails at 79.95% vs `--cov-fail-under=80` | `backend/pyproject.toml:73` | Minor/build |
| 10.4 | Add Business form has no live checksum feedback | `frontend/app/(client)/app/businesses/page.tsx` — checksum validated only inside `addBusiness()` after click | Minor UX |

## Task contracts

### 10.1 — Fix FY month rollover (backend)
`get_this_fy_period_statuses()` must produce the 12 real `MMYYYY` filing periods of the Indian FY
(Apr→Mar). Months 4–12 map to `fy_start_year`; months 13–15 roll to Jan–Mar of `fy_start_year + 1`
(`012027`, `022027`, `032027` for FY 2026-27). No `13`/`14`/`15` month index may survive.
`fp` regex stays `^(0[1-9]|1[0-2])(20\d{2})$`.

### 10.2 — Shared client shell layout (frontend)
Create `frontend/app/(client)/app/layout.tsx` that renders `<ShellNav>` exactly once for every route
under `(client)/app`. It performs `silentRefresh()` + `fetchMe()` on mount to feed
`userName`/`gstAccounts`/`onSignOut`. Remove the now-duplicate per-page `<ShellNav>` from the pages
that already embed it (dashboard, profile, settings, businesses, businesses/[gstin], itc) so no
double header renders. Preserve every existing testid and the sign-out/GSTIN-switcher behaviour.

### 10.3 — Cross the 80% coverage gate (backend)
Add targeted unit tests covering the uncovered lines so `pytest` with the default
`--cov-fail-under=80` addopts passes at >= 80.00% (no `--no-cov` escape). Full suite green, ruff+mypy clean.

### 10.4 — Live checksum feedback (frontend)
While the GSTIN input holds 15 chars, validate the mod-36 check digit live and render an inline
error/tooltip the moment it is invalid (not only after submit). Keep the existing
`business-add-*` testids and the submit-button gating for non-15-char input unchanged.

### 10.5 — Phase-10 E2E + full regression (3-lens)
`scripts/e2e_phase10.py` green in one run (pytest/ruff/mypy; tsc/lint/playwright; GST-domain),
all 10.1–10.4 fixes verified, tracker regenerated, reachability audit includes shell nav on workspace routes.

## Out of scope (flag for Tony, do NOT build)
- DPDP "Export My Data" UI button (backend `/api/v1/dpdp/export` exists, no screen yet).
- Quarterly-vs-monthly scheme indication in the FY grid (QRMP/composition).
