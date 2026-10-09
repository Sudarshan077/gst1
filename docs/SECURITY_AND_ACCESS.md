# Security & Access Specification

> **Status:** v1.0 (2026-09-26) · Owner doc for AuthN/AuthZ, consent, DPDP compliance, audit, secrets
> **Model detail:** TECHNICAL_ARCHITECTURE.md §3 · **Endpoints:** API_SPECIFICATION.md

---

## 1. Authentication

| Concern | Control |
|---|---|
| Identity | Email (OTP or password) is the primary login. One person = one `users` row. Mobile optional. GSTIN is NEVER a login identifier (printed on every invoice — semi-public) |
| OTP | 6-digit, 5-minute expiry, Redis-stored with attempt counter; rate limit 5/hour/identifier; dev mode = email OTP (SMS provider Phase 1) |
| Session | JWT access 15 min + rotating refresh token 7 days; refresh rotation detected (reuse of a rotated token kills the family) |
| Passwords | argon2id; only for users who opt into password login; never required |
| 2FA | TOTP optional for any user wanting extra security — setup flow: QR + verify code |
| Step-up auth | Fresh OTP required for: export generation, link revocation, member invites, DPDP erasure, TOTP reset |
| Brute force | Per-identifier + per-IP limits in Redis; exponential backoff; lockout notification via email |

## 2. Authorization

| Rule | Enforcement |
|---|---|
| Users see only GSTINs where `user_gst_access` grants them ADMIN/FILER/VIEWER | Single FastAPI dependency (`require_gstin_access`) — never per-route ad-hoc checks |
| Role-based permissions: ADMIN (full access + invite), FILER (upload/file), VIEWER (read-only) | Checked by the same dependency, declared per route |
| A user cannot browse GSTINs they don't have access to | Enforced at service layer; covered by an explicit test |
| Every filing object resolves through a `gstin` → gst_accounts → user_gst_access chain | No endpoint accepts a raw GSTIN without the guard |
| Locked periods: FILED periods reject invoice/CDN mutations; amendments are delta records only | Service-layer rule + test |
| Profile is self-service but minimal: only `full_name` is patchable; `email` is read-only by schema (`extra="forbid"` → 422, never silent) (PHASE8 8.1) | Pydantic validation layer + test |
| Settings writes never duplicate logic: `PATCH /me/settings` delegates to the notification-prefs handler — one validation path, one transaction, one audit surface (PHASE8 8.2) | Single-handler delegation, integration-tested |
| Business edits (`PATCH /gst-accounts/{gstin}`) require FILER/ADMIN; VIEWER → 403; unknown GSTIN → 404 `GSTIN_NOT_FOUND` (existence is data) (PHASE8 8.3) | `require_gstin_access` guard + matrix tests |

## 3. Data protection

| Concern | Control |
|---|---|
| Transport | TLS everywhere (dev: localhost, self-signed permitted; prod: real certs, HSTS) |
| At rest | PG + MinIO on-host volumes encrypted at the disk level; LLM raw outputs (which contain bill content) stored in the `extraction` schema, access-guarded identically |
| Documents | MinIO presigned URLs, 30-min expiry; no public buckets; keys `{gstin}/{fp}/{docId}` |
| Integrity | sha256 on every document at upload; versioned bucket + `mc mirror` replication + integrity-verify job |
| Secrets | `.env` (never committed) + `.env.example` maintained; redacted tool output restored byte-exact from git/`.bak` per standing rule |
| PII minimization | OCR text retained (evidentiary), never rendered cross-business; supplier/buyer contact details stored only as needed for returns |

## 4. Consent & DPDP Act 2023

| Obligation | Implementation |
|---|---|
| Lawful basis | Terms of service accepted at signup; per-GSTIN access is audit-logged |
| Withdrawal | Access revoke = instant death via user_gst_access deletion; audit logged |
| Data-principal rights | (a) Self-service export: all GSTIN data machine-readable (JSON+CSV+documents manifest); (b) erasure request → workflow with 30-day SLA, legal-retention carve-out documented (GST records must be retained — erasure applies to platform copies beyond statutory retention, default 8 FYs) |
| Breach | 72-hour notification runbook (detect → assess → notify principals) in docs/COMPLIANCE runbook section of this doc's Phase-3 update |
| Roles | GSTIN owner = data principal; platform = data processor |
| Retention | Default 8 FYs (GST law floor); retention job flags + purge workflow Phase 3 |

## 5. Audit

| Event | Logged fields |
|---|---|
| GSTIN access grant / revoke | actor, gstin, target user, role |
| Document upload / view / download | actor, gstin, doc |
| Invoice confirm / edit | actor, gstin, payload_diff (JSONB) |
| Export generation / download | actor, gstin, fp, schema_version |
| Amendment create / export | actor, gstin, deltas |
| Auth events: login, OTP fail-storm, TOTP enable | actor, ip, user-agent |
| Profile update (`PATCH /me/profile`) | actor; event `PROFILE_UPDATED` (PHASE8 8.1) |
| Business (GSTIN) field edits (`PATCH /gst-accounts/{gstin}`) | actor, gstin, changed fields (PHASE8 8.3) |

Audit rows are append-only; no update/delete paths exist in code; DB role has INSERT-only grant on `audit_logs` (migration-enforced).

## 6. Application hardening

| Layer | Control |
|---|---|
| API | Pydantic validation on every input (AI mistakes fail fast); request size caps (upload 25 MB/file); CORS locked to the frontend origin |
| Uploads | Magic-byte type check (not extension); page-count cap; sha256 dedupe |
| LLM calls | Pinned model; prompt-injection defense: OCR text is wrapped as untrusted data, model output validated against the Pydantic extraction schema, unknown fields dropped |
| Rate limits | Global + per-user (Redis); extraction queue caps |
| Dependencies | `pip-audit` in CI; lockfile committed |
| Frontend | No tokens in localStorage (httpOnly refresh cookie); CSP headers |

## 7. Testing the security layer

| Test | Type |
|---|---|
| OTP rate limit + expiry | Unit + integration |
| JWT refresh rotation + reuse kill | Integration |
| TOTP enforcement for firm members | Integration |
| Cross-tenant access attempts (CA→unlinked business, client→other business) return 403/404, never data | Integration, matrix-parameterized |
| Locked-period mutation rejection | Integration |
| GSTIN search on unlinked business leaks no data | Integration (response-shape assertion) |
| Audit append-only (UPDATE/DELETE fails) | Migration test |
| Step-up auth on export/revoke/invite/erasure | Integration |

See TESTING_STRATEGY.md §4 for the full gate wiring.