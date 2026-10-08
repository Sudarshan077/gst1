"""Seed a FilingPeriod row for the Phase-8 dashboard status-grid spec (8.10).

Test fixture, not product code. The public API has no endpoint that sets
READY_FOR_FILING (only OPEN -> FILED transitions exist on /returns/filed and
the GSP file routes), and the 8.10 grid must render all three tracker states
(filed / draft / pending) for a seeded GSTIN. The backend's own pytest suite
seeds the same rows through api_sessionmaker (test_business_mgmt_overview.py);
this script is the E2E-process equivalent, invoked by
frontend/tests/phase8-dashboard-status-grid.spec.ts.

Run with the BACKEND venv from the repo root while the backend is up on :8084:
    backend/.venv/Scripts/python.exe scripts/seed_period_status.py \\
        <gstin> <fp> <OPEN|READY_FOR_FILING|FILED>

Only INSERTs-or-updates the one named period row; never deletes anything.
"""

from __future__ import annotations

import asyncio
import sys

from app.db.models.gst import FilingPeriod, FilingStatus
from app.db.session import get_sessionmaker


async def seed(gstin: str, fp: str, status: str) -> int:
    st = FilingStatus(status.upper())
    maker = get_sessionmaker()
    async with maker() as session:
        existing = await session.get(FilingPeriod, (gstin, fp))
        if existing is None:
            session.add(
                FilingPeriod(
                    gstin=gstin,
                    fp=fp,
                    scheme_snapshot="REGULAR_MONTHLY",
                    status=st,
                )
            )
        else:
            existing.status = st
        await session.commit()
        row = await session.get(FilingPeriod, (gstin, fp))
        assert row is not None
        return row.status.value


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        sys.stderr.write(__doc__)
        sys.exit(2)
    gstin, fp, status = argv[1], argv[2], argv[3]
    result = asyncio.run(seed(gstin, fp, status))
    print(result)


if __name__ == "__main__":
    main(sys.argv)
