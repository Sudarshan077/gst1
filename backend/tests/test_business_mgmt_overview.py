"""Task 8.3 — business (GSTIN) management completion (PHASE8 §3.3).

Covers: PATCH legal_name as ADMIN → 200 + one GSTIN_UPDATED audit row with a
before/after diff; PATCH as VIEWER → 403 (guard contract unchanged —
AccessDenied → 404 GSTIN_NOT_FOUND, PermissionDenied → 403);
GET /gst-accounts/{gstin}/overview → detail + this-FY periods with statuses.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.auth.tokens import verify_access_token
from app.db.models.core import AccessRole, AuditLog, User
from app.db.models.gst import FilingPeriod, FilingStatus
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_email, register_and_login
from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


def _headers(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _grant(
    sessionmaker: SessionMaker,
    owner_id: Any,
    gstin: str,
    user_id: Any,
    role: AccessRole,
) -> None:
    """Grant `user_id` a role on `gstin` (service path, like the matrix tests)."""
    from app.core.gst_accounts import service as gstin_service

    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        email = f"{role.value.lower()}+{user_id}@example.com"
        user.email = email
        await session.commit()
        await gstin_service.add_collaborator(
            session,
            gstin,
            email=email,
            role=role,
            actor_user_id=owner_id,
        )


async def test_patch_legal_name_as_admin_200_and_audit_row(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """PATCH {legal_name} as ADMIN → 200, persisted, one GSTIN_UPDATED audit
    row with before/after legal_name and the ADMIN actor recorded."""
    tokens, account = await seed_account(client, api_sessionmaker)
    user_id = verify_access_token(tokens["access_token"])
    old_name = account.legal_name
    new_name = "Gowda Enterprises LLP"

    resp = await client.patch(
        f"/api/v1/gst-accounts/{account.gstin}",
        headers=_headers(tokens),
        json={"legal_name": new_name},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["legal_name"] == new_name
    # identity fields are never touched by a business-fields patch
    assert body["data"]["gstin"] == account.gstin
    assert body["data"]["pan"] == account.pan

    # persisted
    detail = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}", headers=_headers(tokens)
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["legal_name"] == new_name

    # exactly one GSTIN_UPDATED audit row, with the diff + actor
    async with api_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "GSTIN_UPDATED",
                        AuditLog.gstin == account.gstin,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1, f"expected 1 GSTIN_UPDATED row, got {len(rows)}"
    log = rows[0]
    assert log.entity == "gst_account"
    assert log.entity_id == account.gstin
    assert log.actor_user_id == user_id
    diff = log.payload_diff or {}
    assert diff["before"]["legal_name"] == old_name
    assert diff["after"]["legal_name"] == new_name


async def test_patch_all_business_fields_round_trip(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """One PATCH carrying legal_name, trade_name, registered_address and
    filing_scheme → all persisted; aato_minor keeps the IRN threshold live."""
    tokens, account = await seed_account(client, api_sessionmaker)

    resp = await client.patch(
        f"/api/v1/gst-accounts/{account.gstin}",
        headers=_headers(tokens),
        json={
            "legal_name": "New Legal Pvt Ltd",
            "trade_name": "New Trade",
            "registered_address": "12 MG Road, Bengaluru 560001",
            "filing_scheme": "QRMP",
            "aato_minor": 6_000_000_000,  # ₹6 crore > ₹5cr → IRN applicable
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["legal_name"] == "New Legal Pvt Ltd"
    assert data["trade_name"] == "New Trade"
    assert data["registered_address"] == "12 MG Road, Bengaluru 560001"
    assert data["filing_scheme"] == "QRMP"
    assert data["aato_latest_minor"] == 6_000_000_000
    assert data["irn_applicable"] is True

    # audit diff covers every editable field
    async with api_sessionmaker() as session:
        log = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "GSTIN_UPDATED",
                        AuditLog.gstin == account.gstin,
                    )
                )
            )
            .scalars()
            .one()
        )
    diff = log.payload_diff or {}
    assert set(diff["after"].keys()) == {
        "legal_name",
        "trade_name",
        "registered_address",
        "aato_latest_minor",
        "filing_scheme",
    }
    assert diff["after"]["filing_scheme"] == "QRMP"


async def test_patch_as_viewer_is_403(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """VIEWER has a grant (so read is 200) but PATCH → 403 FORBIDDEN —
    PermissionDenied path of the unchanged guard contract."""
    owner_tokens, account = await seed_account(client, api_sessionmaker)
    owner_id = verify_access_token(owner_tokens["access_token"])

    viewer_tokens = await register_and_login(client, make_email())
    viewer_id = verify_access_token(viewer_tokens["access_token"])
    await _grant(
        api_sessionmaker, owner_id, account.gstin, viewer_id, AccessRole.VIEWER
    )

    # read works for VIEWER — the plain access guard (months summary is
    # VIEWER-readable; the detail route is export-guarded by design)
    read = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}/overview",
        headers=_headers(viewer_tokens),
    )
    assert read.status_code == 200, read.text

    # write is denied: 403 FORBIDDEN, not 404 (grant exists; role missing)
    patched = await client.patch(
        f"/api/v1/gst-accounts/{account.gstin}",
        headers=_headers(viewer_tokens),
        json={"legal_name": "Should Not Persist"},
    )
    assert patched.status_code == 403, patched.text
    assert patched.json()["error"]["code"] == "FORBIDDEN"

    # nothing changed, no audit row
    detail = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}", headers=_headers(owner_tokens)
    )
    assert detail.json()["data"]["legal_name"] == account.legal_name
    async with api_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "GSTIN_UPDATED",
                        AuditLog.gstin == account.gstin,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


async def test_patch_unknown_gstin_is_404_gstin_not_found(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """No grant → 404 GSTIN_NOT_FOUND (AccessDenied path; existence is data)."""
    tokens, _ = await seed_account(client, api_sessionmaker)
    fake = make_gstin()

    resp = await client.patch(
        f"/api/v1/gst-accounts/{fake}",
        headers=_headers(tokens),
        json={"legal_name": "Nope"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "GSTIN_NOT_FOUND"
    # zero tenant data leaks
    assert "Test Enterprise" not in resp.text


async def test_patch_requires_auth(client: AsyncClient) -> None:
    """No bearer token → 401 (guard contract)."""
    resp = await client.patch(
        f"/api/v1/gst-accounts/{make_gstin()}", json={"legal_name": "X"}
    )
    assert resp.status_code == 401


async def test_overview_returns_detail_and_this_fy_period_statuses(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """GET /overview → account detail + this-FY periods, each with a status;
    seeded statuses (FILED / READY_FOR_FILING / OPEN) are surfaced verbatim."""
    tokens, account = await seed_account(client, api_sessionmaker)

    # Seed three periods in the CURRENT FY with distinct statuses.
    from datetime import date as _date

    today = _date.today()
    fy_start = today.year if today.month >= 4 else today.year - 1
    fps = [(4, fy_start), (5, fy_start), (6, fy_start)]  # Apr/May/Jun
    statuses = [FilingStatus.FILED, FilingStatus.READY_FOR_FILING, FilingStatus.OPEN]
    async with api_sessionmaker() as session:
        for (m, y), st in zip(fps, statuses, strict=True):
            session.add(
                FilingPeriod(
                    gstin=account.gstin,
                    fp=f"{m:02d}{y}",
                    scheme_snapshot="REGULAR_MONTHLY",
                    status=st,
                )
            )
        await session.commit()

    resp = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}/overview", headers=_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["gstin"] == account.gstin
    assert data["fy"].startswith(str(fy_start))
    # detail carries the same account shape as GET /gst-accounts/{gstin}
    assert data["detail"]["legal_name"] == account.legal_name
    assert data["detail"]["pan"] == account.pan

    periods = data["periods"]
    assert len(periods) == 12, "a full FY is 12 periods (Apr..Mar)"
    by_fp = {p["fp"]: p for p in periods}
    for (m, y), st in zip(fps, statuses, strict=True):
        assert by_fp[f"{m:02d}{y}"]["status"] == st.value
    # every period row carries a status
    assert all(p["status"] in ("OPEN", "READY_FOR_FILING", "FILED") for p in periods)


async def test_overview_viewer_reads_outsider_404(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Overview is a read: VIEWER gets 200; an outsider gets 404 GSTIN_NOT_FOUND."""
    owner_tokens, account = await seed_account(client, api_sessionmaker)
    owner_id = verify_access_token(owner_tokens["access_token"])

    viewer_tokens = await register_and_login(client, make_email())
    viewer_id = verify_access_token(viewer_tokens["access_token"])
    await _grant(
        api_sessionmaker, owner_id, account.gstin, viewer_id, AccessRole.VIEWER
    )

    ok = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}/overview",
        headers=_headers(viewer_tokens),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["gstin"] == account.gstin

    outsider_tokens = await register_and_login(client, make_email())
    denied = await client.get(
        f"/api/v1/gst-accounts/{account.gstin}/overview",
        headers=_headers(outsider_tokens),
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "GSTIN_NOT_FOUND"


async def test_overview_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/gst-accounts/{make_gstin()}/overview")
    assert resp.status_code == 401
