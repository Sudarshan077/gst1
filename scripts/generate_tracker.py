"""Regenerate docs/BUILD_TRACKER.md from the build loop's plan.json + state.json.

Run from the repo root:
    python scripts/generate_tracker.py

Idempotent: reads build/plan.json (phases -> tasks) and build/state.json
(tasks{id:{status}}), writes docs/BUILD_TRACKER.md, prints the byte count.
Commit docs/BUILD_TRACKER.md (+ README.md if the pointer is missing) and push.

NOTE: build/plan.json and build/state.json are gitignored (agent build-loop
artifacts). If they are absent on a fresh clone, this script cannot run — the
committed docs/BUILD_TRACKER.md is then the authoritative record.
"""

from __future__ import annotations

import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAN = ROOT / "build" / "plan.json"
STATE = ROOT / "build" / "state.json"
OUT = ROOT / "docs" / "BUILD_TRACKER.md"
REPO = "github.com/Sudarshan077/gst1"


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8"))

    done = {tid for tid, t in state.get("tasks", {}).items() if t.get("status") == "done"}
    current = state.get("current_task")
    phases = plan["phases"]
    total = sum(len(ph["tasks"]) for ph in phases)
    ndone = sum(1 for ph in phases for t in ph["tasks"] if t["id"] in done)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M IST")

    L: list[str] = []
    L.append("# GST Filing App — Build Tracker\n")
    L.append(f"**Repo:** `{REPO}` · **Branch:** `main`  ")
    L.append(
        "**Stack:** Python 3.11 (FastAPI · SQLAlchemy · Alembic · PostgreSQL) backend · "
        "Next.js 16 + TypeScript (App Router · Tailwind · shadcn/ui) frontend  "
    )
    L.append(
        "**Build mode:** 3-agent loop — Builder / Tester / Monitor. Every task is independently "
        "verified by the Tester (real command output: pytest, ruff, mypy, tsc, Playwright) before "
        "the Monitor may ADVANCE it. Backend and frontend are built together in the same loop.  "
    )
    L.append(f"**Last updated:** {now}  ")
    L.append(f"**Progress:** **{ndone} / {total} tasks done ({ndone * 100 // total}%)**\n")
    L.append("---\n")

    L.append("## Phase summary\n")
    L.append("| Phase | Name | Tasks | Done | Remaining | Status |")
    L.append("|---|---|---|---|---|---|")
    for ph in phases:
        ts = ph["tasks"]
        d = sum(1 for t in ts if t["id"] in done)
        if d == len(ts):
            st = "✅ Complete"
        elif d > 0 or any(t["id"] == current for t in ts):
            st = "🔄 In progress"
        else:
            st = "⬜ Not started"
        L.append(f"| {ph['id']} | {ph['name']} | {len(ts)} | {d} | {len(ts) - d} | {st} |")
    L.append(f"| **Total** | | **{total}** | **{ndone}** | **{total - ndone}** | |")
    L.append("\n---\n")

    L.append("## Full task ledger\n")
    for ph in phases:
        L.append(f"### Phase {ph['id']} — {ph['name']}\n")
        L.append("| ID | Task | Status | Source docs |")
        L.append("|---|---|---|---|")
        for t in ph["tasks"]:
            if t["id"] in done:
                st = "✅ Done"
            elif t["id"] == current:
                st = "🔄 In progress"
            else:
                st = "⬜ Not started"
            docs = ", ".join(f"`{d.split('/')[-1]}`" for d in t.get("docs", []))
            L.append(f"| {t['id']} | {t['title']} | {st} | {docs} |")
        L.append("")
    L.append("---\n")

    L.append("## Definition of done (per task)\n")
    L.append("A task counts as Done only when all of these hold:\n")
    L.append("| Gate | Command | Must be |")
    L.append("|---|---|---|")
    L.append("| Backend tests | `cd backend && ./.venv/Scripts/python.exe -m pytest tests/` | all pass |")
    L.append("| Lint | `ruff check .` | clean |")
    L.append("| Types | `mypy .` | clean |")
    L.append("| Frontend types | `cd frontend && npx tsc --noEmit` | clean |")
    L.append("| Frontend lint | `npm run lint` | clean |")
    L.append("| E2E (where specified) | `npx playwright test` | pass |")
    L.append(
        "\nIndependent Tester re-runs these against the live tree; Monitor ADVANCEs only on "
        "`evidence=REAL`.\n"
    )
    L.append("---\n")
    L.append("## How to read this file\n")
    L.append(
        "This tracker is the single source of truth, generated from the build loop's "
        "`plan.json` + `state.json` by `scripts/generate_tracker.py`. It is regenerated and "
        "re-committed at every phase boundary, so the GitHub page never drifts from real "
        "progress. Task-level evidence (tester verdicts, defect reports, commits) lives in the "
        "git history and in `docs/GST_BUILD_STATUS.md`.\n"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(L)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text)} bytes) — {ndone}/{total} tasks done")


if __name__ == "__main__":
    main()
