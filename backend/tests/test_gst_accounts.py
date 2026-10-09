"""GST account CRUD + this-FY filing period statuses.

Phase 10.1 regression cover: the FY grid must emit the 12 real `MMYYYY`
periods of the Indian FY (Apr..Dec of the start year, Jan..Mar of the next),
never the non-existent month indexes 13/14/15.
"""

import re

import pytest
from app.core.gst_accounts import service as gst_accounts_service
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker, make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account

FP_REGEX = r"^(0[1-9]|1[0-2])(20\d{2})$"


# Use pytest-asyncio to run async tests
@pytest.mark.asyncio
async def test_gst_accounts_crud(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    # 1. Create user and log in
    mobile = make_mobile()
    auth_data = await register_and_login(client, mobile)
    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create GST Account
    gstin = make_gstin()
    response = await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={
            "gstin": gstin,
            "legal_name": "Test Company",
            "trade_name": "Test Trade Name",
        },
    )
    assert response.status_code == 200

    # 3. List
    response = await client.get("/api/v1/gst-accounts", headers=headers)
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1

    # 4. Get
    response = await client.get(f"/api/v1/gst-accounts/{gstin}", headers=headers)
    assert response.status_code == 200

    # 5. Patch
    response = await client.patch(
        f"/api/v1/gst-accounts/{gstin}", headers=headers, json={"trade_name": "New Trade Name"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["trade_name"] == "New Trade Name"


def test_fy_periods_for_year_exact_12_strings() -> None:
    """FY 2026-27 → 042026..122026 then 012027/022027/032027, exactly 12 rows."""
    assert gst_accounts_service.fy_periods_for_year(2026) == [
        "042026",
        "052026",
        "062026",
        "072026",
        "082026",
        "092026",
        "102026",
        "112026",
        "122026",
        "012027",
        "022027",
        "032027",
    ]


@pytest.mark.parametrize("fy_start_year", [2025, 2026, 2027, 2030])
def test_fy_periods_never_emit_month_index_13_to_15(fy_start_year: int) -> None:
    """No '13'/'14'/'15' month index may survive; every fp is a valid MMYYYY."""
    fps = gst_accounts_service.fy_periods_for_year(fy_start_year)
    assert len(fps) == 12
    assert len(set(fps)) == 12  # no duplicates across the year rollover
    for fp in fps:
        assert re.match(FP_REGEX, fp), fp
        assert fp[:2] not in {"13", "14", "15", "00"}
    # Apr..Dec carry the start year; Jan..Mar roll to the next calendar year.
    assert fps[:9] == [f"{m:02d}{fy_start_year}" for m in range(4, 13)]
    assert fps[9:] == [f"{m:02d}{fy_start_year + 1}" for m in range(1, 4)]


def test_current_fy_start_year_rolls_at_april() -> None:
    from datetime import date

    assert gst_accounts_service.current_fy_start_year(date(2026, 3, 31)) == 2025
    assert gst_accounts_service.current_fy_start_year(date(2026, 4, 1)) == 2026
    assert gst_accounts_service.current_fy_start_year(date(2027, 1, 15)) == 2026
    assert gst_accounts_service.current_fy_start_year() == (
        date.today().year if date.today().month >= 4 else date.today().year - 1
    )


async def test_overview_periods_are_the_12_real_fy_months(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """GET /overview returns exactly the 12 valid FY fps — the DB sees no 13/14/15.

    The seeded row sits on a *rolled-over* month (January of the next calendar
    year, e.g. `012027` for FY 2026-27), proving the lookup query uses the
    rolled fps and its status is surfaced verbatim.
    """
    from app.db.models.gst import FilingPeriod, FilingStatus

    tokens, account = await seed_account(client, api_sessionmaker)

    start = gst_accounts_service.current_fy_start_year()
    expected = gst_accounts_service.fy_periods_for_year(start)
    rolled_fp = f"01{start + 1}"  # January of the following calendar year
    async with api_sessionmaker() as session:
        session.add(
            FilingPeriod(
                gstin=account.gstin,
                fp=rolled_fp,
                scheme_snapshot="REGULAR_MONTHLY",
                status=FilingStatus.FILED,
            )
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}/overview",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    fps = [p["fp"] for p in data["periods"]]
    assert fps == expected
    assert len(fps) == 12
    assert data["fy"] == f"{start}-{str(start + 1)[-2:]}"
    for fp in fps:
        assert re.match(FP_REGEX, fp), fp
    by_fp = {p["fp"]: p for p in data["periods"]}
    assert by_fp[rolled_fp]["status"] == "FILED"
    # a month with no seeded period reports OPEN
    assert by_fp[expected[0]]["status"] == "OPEN"
