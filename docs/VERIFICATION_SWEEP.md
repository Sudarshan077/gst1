# Verification Sweep — rules for Phase 0..5 re-test (Tony, 6 Oct 2026)

Scope: every prior phase's deliverables were built by OmniRoute models. We now rebuild confidence with the elite ollama-cloud chain (kimi-k2.7-code builder, glm-5.3-flash tester, deepseek-v4.1-flash monitor). Treat each phase's work as UNVERIFIED until this sweep says otherwise.

## How the tester must judge each phase

For phase N, run THREE lenses. All three must PASS, each with REAL command evidence (paste exact commands + outputs, file:line references). A PASS on a summary alone is not accepted.

### Lens 1 — Code (backend correctness)
- Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --no-header -p no:cacheprovider`, filtered to the phase's modules plus the phase's e2e script in `scripts/e2e_phase<N>.py` when present.
- Also: `ruff check backend/` and `mypy backend/` green.
- Verify the phase's `done_when` strings from `build/plan.json` hold TRUE on live state (not "looked at the code" — run, confirm, paste counts).
- Money is integer paise; assert one phase-2 task by calculating a money total on a fixture by hand.

### Lens 2 — Frontend / user flow
- Boot the frontend (`cd frontend && npm run dev` or the configured port 9094) and walk the user-visible surfaces of the phase: login/register/upload/dashboard screens that phase delivered. Use Playwright or browser automation; report the URLs exercised.
- Confirm no role-selection / multi-role split is required from the user — per the new design (Phase 7), only ONE user type exists. If a screen still asks about role (CA vs business owner), FAIL with the route + component name.

### Lens 3 — GST domain correctness
- Sanity-check the phase's domain logic against the spec docs (docs/GST_RULES.md, docs/API_REFERENCE.md, docs/DB_SCHEMA.md as applicable): GSTR-1 sections, mod-36 GSTIN checksum, paise arithmetic, period locking, 423 locked-period response, refresh-token reuse detection.
- No fabricated GSTINs in fixtures beyond the documented mod-36-valid synthetic set.

## Monitor rule

- ADVANCE only when all three lenses PASS with real evidence.
- RETRY when any lens fails; BUILDER_INSTRUCTION names the exact paths/commands the builder must touch. Do NOT accept "it seems fine".
- ESCALATE only when the defect exceeds the task's retry budget or is a design gap needing a human decision.

## Phase map (what each `6.x` task covers)
- 6.1 → Phase 0 (skeleton + auth + GST accounts + web shell)
- 6.2 → Phase 1 (capture & correlation: upload, extraction, review, access mgmt, dashboards)
- 6.3 → Phase 2 (returns engine: GSTR-1, CDNR/CDNUR, GSTR-3B, 2B/ITC, GSTR-1A, deadline engine)
- 6.4 → Phase 3 (firm scale & compliance: multi-client, permissions, notifications, DPDP, CMP-08/GSTR-4)
- 6.5 → Phase 4 (direct filing: GSP adapter, live IRP, sandbox filing)
- 6.6 → Phase 5 (deployment, GSP/IRP onboarding, security hardening, DPDP retention, UAT)

Do NOT modify any production code during verification — a failure becomes a monitor RETRY with an exact fix list for the builder.
