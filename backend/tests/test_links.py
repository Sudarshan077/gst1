"""Test Task 1.4 — CA-firm <-> client linking (both flows) + consent + audit (E2E)."""

from __future__ import annotations

import random
import string
import uuid
from typing import Any

import pytest
from app.db.models.core import (
    AuditLog,
    Business,
    BusinessRole,
    BusinessUser,
    CaClientLink,
    CaFirm,
    CaFirmMember,
    ConsentRecord,
    FilingScheme,
    FirmRole,
    GstRegistration,
    LinkInitiatedBy,
    LinkStatus,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import register_and_login
from tests.gstin_fixtures import gstin_checksum_valid, make_gstin, make_pan

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


def _mobile() -> str:
    return "9" + "".join(random.choices(string.digits, k=9))  # noqa: S311


async def _seed_business(sessionmaker: SessionMaker) -> tuple[Business, GstRegistration]:
    pan = make_pan()
    gstin = make_gstin(pan=pan)
    assert gstin_checksum_valid(gstin)

    async with sessionmaker() as session:
        biz = Business(pan=pan, legal_name=f"Test Business {uuid.uuid4().hex[:6]}")
        session.add(biz)
        await session.flush()

        reg = GstRegistration(
            business_id=biz.id,
            gstin=gstin,
            state_code="27",
            filing_scheme=FilingScheme.REGULAR_MONTHLY,
        )
        session.add(reg)
        await session.commit()
        await session.refresh(biz)
        await session.refresh(reg)
        return biz, reg


async def _seed_firm(sessionmaker: SessionMaker, user_id: uuid.UUID) -> CaFirm:
    async with sessionmaker() as session:
        firm = CaFirm(
            firm_name=f"Test Firm {uuid.uuid4().hex[:6]}",
            ca_code=f"CA{uuid.uuid4().hex[:8].upper()}",
            pan=make_pan(),
        )
        session.add(firm)
        await session.commit()
        await session.refresh(firm)

        member = CaFirmMember(
            firm_id=firm.id,
            user_id=user_id,
            role=FirmRole.PARTNER,
            can_export=True,
            can_revoke=True,
            can_invite_members=True,
        )
        session.add(member)
        await session.commit()
        return firm


# ------------------------------------------------------------------ Tests


async def test_flow_a_firm_requests_client_by_gstin(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Flow A: CA firm requests client link by GSTIN (no business data leak)."""
    firm_auth = await register_and_login(client, _mobile())
    firm_user_id = uuid.UUID(firm_auth["user"]["id"])
    firm_headers = {"Authorization": f"Bearer {firm_auth['access_token']}"}
    firm = await _seed_firm(api_sessionmaker, firm_user_id)

    biz, reg = await _seed_business(api_sessionmaker)

    # 1. Firm requests client by GSTIN
    res = await client.post(
        "/api/v1/firm/clients/request",
        headers=firm_headers,
        json={"gstin": reg.gstin},
    )
    assert res.status_code == 200, f"Flow A request failed: {res.text}"
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "PENDING"
    link_id = body["data"]["id"]

    # Verify link in DB
    async with api_sessionmaker() as session:
        link = await session.get(CaClientLink, uuid.UUID(link_id))
        assert link is not None
        assert link.ca_firm_id == firm.id
        assert link.business_id == biz.id
        assert link.status == LinkStatus.PENDING
        assert link.initiated_by == LinkInitiatedBy.FIRM_REQUEST

        # Verify audit row created
        audit_row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.entity == "ca_client_links",
                    AuditLog.entity_id == link_id,
                    AuditLog.action == "LINK_REQUEST",
                )
            )
        ).scalar_one_or_none()
        assert audit_row is not None
        assert audit_row.actor_user_id == firm_user_id

    # 2. Non-existent GSTIN leaks NO data (404)
    fake_gstin = make_gstin(pan=make_pan())
    res_fake = await client.post(
        "/api/v1/firm/clients/request",
        headers=firm_headers,
        json={"gstin": fake_gstin},
    )
    assert res_fake.status_code == 404


async def test_flow_b_client_invite_code_generates_and_redeems(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Flow B: Client generates invite code (7-day single use), firm redeems it."""
    # Client owner
    client_auth = await register_and_login(client, _mobile())
    client_user_id = uuid.UUID(client_auth["user"]["id"])
    client_headers = {"Authorization": f"Bearer {client_auth['access_token']}"}

    biz, reg = await _seed_business(api_sessionmaker)
    async with api_sessionmaker() as session:
        session.add(
            BusinessUser(business_id=biz.id, user_id=client_user_id, role=BusinessRole.OWNER)
        )
        await session.commit()

    # Firm partner
    firm_auth = await register_and_login(client, _mobile())
    firm_user_id = uuid.UUID(firm_auth["user"]["id"])
    firm_headers = {"Authorization": f"Bearer {firm_auth['access_token']}"}
    await _seed_firm(api_sessionmaker, firm_user_id)

    # 1. Client generates invite code
    res = await client.post(
        "/api/v1/links/invite-code",
        headers=client_headers,
        json={"business_id": str(biz.id)},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    code = data["invite_code"]
    assert code.startswith("INV-")
    assert "expires_at" in data

    # 2. Firm redeems code
    res_redeem = await client.post(
        "/api/v1/firm/clients/redeem",
        headers=firm_headers,
        json={"invite_code": code},
    )
    assert res_redeem.status_code == 200, res_redeem.text
    redeem_data = res_redeem.json()["data"]
    assert redeem_data["status"] == "ACTIVE"
    assert redeem_data["business_id"] == str(biz.id)
    assert redeem_data["consent_record_id"] is not None

    # 3. Single-use: second redeem fails
    res_repeat = await client.post(
        "/api/v1/firm/clients/redeem",
        headers=firm_headers,
        json={"invite_code": code},
    )
    assert res_repeat.status_code == 400


async def test_link_lifecycle_consent_accept_reject_revoke(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Link lifecycle: Flow A request -> Client accept (consent v1.0) -> Revoke (instant death)."""
    # Setup client + business
    client_auth = await register_and_login(client, _mobile())
    client_user_id = uuid.UUID(client_auth["user"]["id"])
    client_headers = {"Authorization": f"Bearer {client_auth['access_token']}"}

    biz, reg = await _seed_business(api_sessionmaker)
    async with api_sessionmaker() as session:
        session.add(
            BusinessUser(business_id=biz.id, user_id=client_user_id, role=BusinessRole.OWNER)
        )
        await session.commit()

    # Setup firm
    firm_auth = await register_and_login(client, _mobile())
    firm_user_id = uuid.UUID(firm_auth["user"]["id"])
    firm_headers = {"Authorization": f"Bearer {firm_auth['access_token']}"}
    await _seed_firm(api_sessionmaker, firm_user_id)

    # 1. Firm requests client link
    res = await client.post(
        "/api/v1/firm/clients/request",
        headers=firm_headers,
        json={"gstin": reg.gstin},
    )
    assert res.status_code == 200
    link_id = res.json()["data"]["id"]

    # 2. Client views incoming links
    res_list = await client.get("/api/v1/links", headers=client_headers)
    assert res_list.status_code == 200
    links = res_list.json()["data"]
    assert any(item["id"] == link_id and item["status"] == "PENDING" for item in links)

    # 3. Client accepts with versioned consent
    res_accept = await client.post(
        f"/api/v1/links/{link_id}/accept",
        headers=client_headers,
        json={"consent_text_version": "v1.0"},
    )
    assert res_accept.status_code == 200
    accept_data = res_accept.json()["data"]
    assert accept_data["status"] == "ACTIVE"
    consent_id = accept_data["consent_record_id"]
    assert consent_id is not None

    async with api_sessionmaker() as session:
        consent = await session.get(ConsentRecord, uuid.UUID(consent_id))
        assert consent is not None
        assert consent.consent_text_version == "v1.0"
        assert consent.withdrawn_at is None

    # 4. Instant access death on revoke
    res_revoke = await client.post(
        f"/api/v1/links/{link_id}/revoke",
        headers=client_headers,
        json={"reason": "Changing accounting firm"},
    )
    assert res_revoke.status_code == 200
    assert res_revoke.json()["data"]["status"] == "REVOKED"

    # Verify link is REVOKED and consent withdrawn
    async with api_sessionmaker() as session:
        link = await session.get(CaClientLink, uuid.UUID(link_id))
        assert link.status == LinkStatus.REVOKED
        assert link.revoked_at is not None

        consent = await session.get(ConsentRecord, uuid.UUID(consent_id))
        assert consent.withdrawn_at is not None
