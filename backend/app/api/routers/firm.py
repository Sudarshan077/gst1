"""CA firm API router (API_SPECIFICATION.md §3)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ServiceError
from app.api.schemas import FirmCreateIn, FirmEnvelope
from app.api.schemas_linking import FirmRequestIn, RedeemIn
from app.core.auth.dependencies import require_user
from app.core.ca_client_links.service import (
    create_firm_request,
    redeem_invite_code,
    revoke_consent_firm,
)
from app.core.firms import service as firm_service
from app.db.models.core import Business, CaClientLink, CaFirmMember, GstRegistration
from app.db.session import get_session

router = APIRouter(prefix="/firm", tags=["firm"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]


@router.post("", response_model=FirmEnvelope)
async def create_firm(
    body: FirmCreateIn, session: SessionDep, user_id: UserDep
) -> dict[str, object]:
    data = await firm_service.create_firm(
        session, user_id, body.firm_name, body.pan
    )
    return {"success": True, "data": data}


@router.post("/clients/request")
async def firm_request_client(
    body: FirmRequestIn, session: SessionDep, user_id: UserDep
) -> dict[str, Any]:
    """Flow A: Firm requests access to client by GSTIN (reveals NO business data)."""
    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    link = await create_firm_request(
        session, member.firm_id, body.get_gstin(), actor_user_id=user_id
    )
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "status": link.status.value,
            "requested_at": link.requested_at.isoformat() if link.requested_at else None,
        },
    }


@router.post("/clients/redeem")
async def firm_redeem_client(
    body: RedeemIn, session: SessionDep, user_id: UserDep
) -> dict[str, Any]:
    """Flow B: Firm redeems client invite code into ACTIVE link."""
    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    link = await redeem_invite_code(
        session, member.firm_id, body.invite_code, actor_user_id=user_id
    )
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "business_id": str(link.business_id),
            "status": link.status.value,
            "consent_record_id": str(link.consent_record_id) if link.consent_record_id else None,
        },
    }


@router.post("/clients/{business_id}/revoke")
async def firm_revoke_client(
    business_id: uuid.UUID, session: SessionDep, user_id: UserDep
) -> dict[str, Any]:
    """Firm revokes access to a client: instant access death."""
    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    link = await revoke_consent_firm(session, member.firm_id, business_id, actor_user_id=user_id)
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "status": link.status.value,
            "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
        },
    }


@router.get("/clients")
async def firm_list_clients(
    session: SessionDep,
    user_id: UserDep,
    query: str | None = Query(None),
    status: str | None = Query(None),
) -> dict[str, Any]:
    """CA roster: list businesses linked to firm."""
    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    stmt = select(CaClientLink).where(CaClientLink.ca_firm_id == member.firm_id)
    if status:
        stmt = stmt.where(CaClientLink.status == status)

    links = (await session.execute(stmt)).scalars().all()
    result = []
    for link in links:
        biz = await session.get(Business, link.business_id)
        if not biz:
            continue
        # If query filter provided, filter by business legal_name or PAN
        if query:
            q = query.lower()
            if q not in biz.legal_name.lower() and q not in biz.pan.lower():
                continue

        regs = (
            await session.execute(
                select(GstRegistration).where(GstRegistration.business_id == biz.id)
            )
        ).scalars().all()

        result.append({
            "link_id": str(link.id),
            "business_id": str(biz.id),
            "legal_name": biz.legal_name,
            "pan": biz.pan,
            "status": link.status.value,
            "registrations": [{"id": str(r.id), "gstin": r.gstin} for r in regs],
        })

    return {"success": True, "data": result}
