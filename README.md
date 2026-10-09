# GST Filing App

GST return filing platform for Indian businesses and CA firms — capture purchase/sale documents, extract line items, reconcile ITC, prepare GSTR-1 / GSTR-3B, and file directly via GSP.

**Stack:** Python 3.11 (FastAPI · SQLAlchemy · Alembic · PostgreSQL · Redis · MinIO) backend · Next.js 16 + TypeScript (App Router · Tailwind · shadcn/ui) frontend

**Build status:** ✅ **Complete — 59 / 59 tasks done** across 9 phases (0–8).

---

## 👉 New here (human or AI)? Start with the handoff guide

**[docs/AI_HANDOFF.md](docs/AI_HANDOFF.md)** — boot the stack, seed demo data, run the app, and the full feature inventory. Everything below is indexed from there.

---

## Repository map

| Folder | What lives here |
|---|---|
| `backend/app/` | FastAPI app — routers, services, DB models, extraction pipeline, auth |
| `backend/tests/` | 41 test modules (243 tests) + shared helpers |
| `backend/alembic/` | DB migrations |
| `frontend/app/` | Next.js App Router screens — `(auth)` login, `(client)/app` shell |
| `frontend/lib/` | Typed API client, session helpers |
| `frontend/tests/` | Playwright E2E specs |
| `scripts/` | `bootstrap_stack.py` (infra), `build_loop.py` (3-agent loop), `seed_demo.py`, `app_tour.cjs`, `generate_tracker.py`, `e2e_phase*.py` |
| `docs/` | All specs, the build tracker, and the demo-screenshots output |
| `test-samples/` | Ready-to-upload invoice fixtures (valid + failure cases) |

---

## Documentation

| Doc | Contents |
|---|---|
| [AI_HANDOFF.md](docs/AI_HANDOFF.md) | **Start here** — boot, seed, run, feature inventory, caveats |
| [TESTING_GUIDE.md](docs/TESTING_GUIDE.md) | Quality gates, test inventory, E2E + API-probe recipes, GST-domain checks |
| [BUILD_TRACKER.md](docs/BUILD_TRACKER.md) | Live progress — phase summary, full task ledger |
| [GST_BUILD_STATUS.md](docs/GST_BUILD_STATUS.md) | Detailed build status + hold record |
| [PRD.md](docs/PRD.md) | Product requirements and user journeys |
| [PHASE8_PRODUCT_COMPLETENESS.md](docs/PHASE8_PRODUCT_COMPLETENESS.md) | Phase-8 scope: gap analysis, task contracts, verification protocol |
| [TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md) | Service layout, schemas, stack decisions |
| [API_SPECIFICATION.md](docs/API_SPECIFICATION.md) | Endpoint contracts |
| [SECURITY_AND_ACCESS.md](docs/SECURITY_AND_ACCESS.md) | Auth model, tenancy isolation, audit rules |
| [FRONTEND_SPECIFICATION.md](docs/FRONTEND_SPECIFICATION.md) | Screens, routes, design tokens |
| [EXTRACTION_SPEC.md](docs/EXTRACTION_SPEC.md) | Document extraction pipeline |
| [TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md) | Test layers and quality gates |
| [VERIFICATION_SWEEP.md](docs/VERIFICATION_SWEEP.md) | 3-lens verification (code / frontend-user / GST-domain) |
| [AI_BUILD_PLAYBOOK.md](docs/AI_BUILD_PLAYBOOK.md) | How the build loop operates |

---

## Quick start

```bash
# 1. Infrastructure — PostgreSQL:5436, Redis:6380, MinIO:9001
backend/.venv/Scripts/python.exe scripts/bootstrap_stack.py --check   # expect 3x OK

# 2. Backend (background terminal)
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --port 8084 --host 127.0.0.1

# 3. Frontend (port 9094)
cd frontend && npm run dev -- --port 9094

# 4. Seed a demo user + GSTINs
backend/.venv/Scripts/python.exe scripts/seed_demo.py

# 5. Guided tour with screenshots
cd frontend && NODE_PATH="D:/gst_filing_app/frontend/node_modules" node ../scripts/app_tour.cjs
```

## Quality gates

Every task passed before it counted as done:

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q   # tests (243 pass, 80% cov)
cd backend && ./.venv/Scripts/python.exe -m ruff check .        # lint (clean)
cd backend && ./.venv/Scripts/python.exe -m mypy .              # types (clean)
cd frontend && npx tsc --noEmit && npm run lint                 # frontend (clean)
cd frontend && npx playwright test                              # E2E (18 specs)
cd /d/gst_filing_app && python scripts/e2e_phase8.py            # 3-lens final gate
```

See [TESTING_GUIDE.md](docs/TESTING_GUIDE.md) for expected results and known coverage/mypy caveats.
