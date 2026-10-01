"""Service layer for CA-firm <-> Client linking (PRD §4.2, SECURITY §2/§4/§5)."""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ServiceError
from app.core.access import audit
from app.core.auth.redis_client import get_redis
from app.db.models.core import (
    BusinessUser,
    CaClientLink,
    ConsentRecord,
    GstRegistration,
    LinkInitiatedBy,
    LinkStatus,
)


@dataclass
class InviteCodeInfo:
    id: str
    invite_code: str
    business_id: str
    client_user_id: str
    expires_at: datetime


async def create_firm_request(
    session: AsyncSession,
    firm_id: uuid.UUID,
    gstin: str,
    actor_user_id: uuid.UUID | None = None,
) -> CaClientLink:
    """Flow A: CA firm requests access to client by GSTIN.
    Zero business data revealed if GSTIN is not found (404 BUSINESS_NOT_FOUND).
    """
    gstin_clean = gstin.strip().upper()
    reg = (
        await session.execute(
            select(GstRegistration).where(GstRegistration.gstin == gstin_clean)
        )
    ).scalar_one_or_none()

    if reg is None:
        raise ServiceError("business not found", 404, "BUSINESS_NOT_FOUND")

    business_id = reg.business_id

    # Check existing link
    existing = (
        await session.execute(
            select(CaClientLink).where(
                CaClientLink.ca_firm_id == firm_id,
                CaClientLink.business_id == business_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == LinkStatus.ACTIVE:
            raise ServiceError("already linked", 409, "ALREADY_LINKED")
        link = existing
        link.status = LinkStatus.PENDING
        link.initiated_by = LinkInitiatedBy.FIRM_REQUEST
        link.requested_at = datetime.now(UTC)
        link.responded_at = None
        link.revoked_at = None
    else:
        link = CaClientLink(
            ca_firm_id=firm_id,
            business_id=business_id,
            status=LinkStatus.PENDING,
            initiated_by=LinkInitiatedBy.FIRM_REQUEST,
            requested_at=datetime.now(UTC),
        )
        session.add(link)

    await session.flush()

    await audit(
        session,
        action="LINK_REQUEST",
        entity="ca_client_links",
        entity_id=str(link.id),
        actor_user_id=actor_user_id,
        ca_firm_id=firm_id,
        business_id=business_id,
        payload_diff={"gstin": gstin_clean, "status": "PENDING"},
    )
    await session.commit()
    return link


async def generate_invite_code(
    session: AsyncSession,
    user_id: uuid.UUID,
    business_id_raw: str | uuid.UUID,
) -> InviteCodeInfo:
    """Flow B: Client generates single-use, 7-day invite code."""
    bid = uuid.UUID(str(business_id_raw)) if isinstance(business_id_raw, str) else business_id_raw

    # Check permission
    bu = (
        await session.execute(
            select(BusinessUser).where(
                BusinessUser.business_id == bid,
                BusinessUser.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if bu is None:
        raise ServiceError("business not found", 404, "BUSINESS_NOT_FOUND")

    code = "INV-" + secrets.token_hex(8).upper()
    expires_at = datetime.now(UTC) + timedelta(days=7)

    redis = get_redis()
    payload = json.dumps({
        "business_id": str(bid),
        "client_user_id": str(user_id),
        "expires_at": expires_at.isoformat(),
        "used": False,
    })
    # 7 days TTL = 604800s
    await redis.set(f"gst:invite:{code}", payload, ex=7 * 86400)

    await audit(
        session,
        action="INVITE_CODE_GENERATED",
        entity="ca_client_links",
        entity_id=code,
        actor_user_id=user_id,
        business_id=bid,
        payload_diff={"invite_code": code, "expires_at": expires_at.isoformat()},
    )
    await session.commit()

    return InviteCodeInfo(
        id=str(uuid.uuid4()),
        invite_code=code,
        business_id=str(bid),
        client_user_id=str(user_id),
        expires_at=expires_at,
    )


async def redeem_invite_code(
    session: AsyncSession,
    firm_id: uuid.UUID,
    invite_code: str,
    actor_user_id: uuid.UUID | None = None,
) -> CaClientLink:
    """Flow B: Firm redeems client invite code into ACTIVE link with versioned consent."""
    redis = get_redis()
    raw = await redis.get(f"gst:invite:{invite_code}")
    if raw is None:
        raise ServiceError("invalid or expired invite code", 404, "INVITE_NOT_FOUND")

    info = json.loads(raw)
    if info.get("used"):
        raise ServiceError("invite code already used", 400, "INVITE_ALREADY_USED")

    # Mark single-use
    info["used"] = True
    await redis.set(f"gst:invite:{invite_code}", json.dumps(info), ex=86400)

    business_id = uuid.UUID(info["business_id"])
    client_user_id = uuid.UUID(info["client_user_id"])

    # Create Consent Record
    consent = ConsentRecord(
        principal_user_id=client_user_id,
        fiduciary_type="CA_FIRM",
        purpose="GST return filing and compliance",
        consent_text_version="v1.0",
        granted_at=datetime.now(UTC),
    )
    session.add(consent)
    await session.flush()

    existing = (
        await session.execute(
            select(CaClientLink).where(
                CaClientLink.ca_firm_id == firm_id,
                CaClientLink.business_id == business_id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is not None:
        link = existing
        link.status = LinkStatus.ACTIVE
        link.initiated_by = LinkInitiatedBy.CLIENT_INVITE
        link.invite_code = invite_code
        link.consent_record_id = consent.id
        link.responded_at = now
        link.revoked_at = None
    else:
        link = CaClientLink(
            ca_firm_id=firm_id,
            business_id=business_id,
            status=LinkStatus.ACTIVE,
            initiated_by=LinkInitiatedBy.CLIENT_INVITE,
            invite_code=invite_code,
            consent_record_id=consent.id,
            requested_at=now,
            responded_at=now,
        )
        session.add(link)

    await session.flush()

    await audit(
        session,
        action="INVITE_CODE_REDEEMED",
        entity="ca_client_links",
        entity_id=str(link.id),
        actor_user_id=actor_user_id,
        ca_firm_id=firm_id,
        business_id=business_id,
        payload_diff={"consent_record_id": str(consent.id), "status": "ACTIVE"},
    )
    await session.commit()
    return link


async def accept_consent(
    session: AsyncSession,
    link_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    consent_version: str = "v1.0",
) -> CaClientLink:
    """Client accepts a pending firm request; creates versioned ConsentRecord."""
    link = await session.get(CaClientLink, link_id)
    if link is None:
        raise ServiceError("link not found", 404, "LINK_NOT_FOUND")

    if link.status != LinkStatus.PENDING:
        raise ServiceError("link is not pending", 400, "LINK_NOT_PENDING")

    # Principal user
    principal_id = actor_user_id
    if principal_id is None:
        bu = (
            await session.execute(
                select(BusinessUser).where(BusinessUser.business_id == link.business_id)
            )
        ).scalars().first()
        principal_id = bu.user_id if bu else uuid.uuid4()

    consent = ConsentRecord(
        principal_user_id=principal_id,
        fiduciary_type="CA_FIRM",
        purpose="GST return filing and compliance",
        consent_text_version=consent_version,
        granted_at=datetime.now(UTC),
    )
    session.add(consent)
    await session.flush()

    link.status = LinkStatus.ACTIVE
    link.consent_record_id = consent.id
    link.responded_at = datetime.now(UTC)

    await audit(
        session,
        action="CONSENT_ACCEPTED",
        entity="ca_client_links",
        entity_id=str(link.id),
        actor_user_id=actor_user_id,
        ca_firm_id=link.ca_firm_id,
        business_id=link.business_id,
        payload_diff={"consent_version": consent_version, "status": "ACTIVE"},
    )
    await session.commit()
    return link


async def reject_consent(
    session: AsyncSession,
    link_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> CaClientLink:
    """Client rejects a pending firm request."""
    link = await session.get(CaClientLink, link_id)
    if link is None:
        raise ServiceError("link not found", 404, "LINK_NOT_FOUND")

    link.status = LinkStatus.REJECTED
    link.responded_at = datetime.now(UTC)

    await audit(
        session,
        action="CONSENT_REJECTED",
        entity="ca_client_links",
        entity_id=str(link.id),
        actor_user_id=actor_user_id,
        ca_firm_id=link.ca_firm_id,
        business_id=link.business_id,
        payload_diff={"status": "REJECTED"},
    )
    await session.commit()
    return link


async def revoke_consent(
    session: AsyncSession,
    link_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> CaClientLink:
    """Client or CA revokes access: instant access death; consent marked withdrawn."""
    link = await session.get(CaClientLink, link_id)
    if link is None:
        raise ServiceError("link not found", 404, "LINK_NOT_FOUND")

    now = datetime.now(UTC)
    link.status = LinkStatus.REVOKED
    link.revoked_at = now

    if link.consent_record_id is not None:
        consent = await session.get(ConsentRecord, link.consent_record_id)
        if consent is not None:
            consent.withdrawn_at = now

    await audit(
        session,
        action="CONSENT_REVOKED",
        entity="ca_client_links",
        entity_id=str(link.id),
        actor_user_id=actor_user_id,
        ca_firm_id=link.ca_firm_id,
        business_id=link.business_id,
        payload_diff={"status": "REVOKED", "revoked_at": now.isoformat()},
    )
    await session.commit()
    return link


async def revoke_consent_firm(
    session: AsyncSession,
    firm_id: uuid.UUID,
    business_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> CaClientLink:
    """CA firm revokes access for a client business."""
    link = (
        await session.execute(
            select(CaClientLink).where(
                CaClientLink.ca_firm_id == firm_id,
                CaClientLink.business_id == business_id,
                CaClientLink.status == LinkStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        raise ServiceError("link not found", 404, "LINK_NOT_FOUND")

    return await revoke_consent(session, link.id, actor_user_id=actor_user_id)
