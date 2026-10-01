"""Client-side linking & consent router (API_SPECIFICATION.md §4)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_linking import (
    ConsentAcceptIn,
    ConsentRevokeIn,
    FirmRequestIn,
    InviteCodeIn,
    RedeemIn,
)
from app.core.access import require_user
from app.core.ca_client_links.service import (
    accept_consent,
    create_firm_request,
    generate_invite_code,
    redeem_invite_code,
    reject_consent,
    revoke_consent,
)
from app.db.models.core import BusinessUser, CaClientLink, CaFirm
from app.db.session import get_session

router = APIRouter(prefix="/links", tags=["ca-client-linking"])


@router.get("")
@router.get("/")
async def list_links(
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
) -> dict[str, Any]:
    """List client's incoming requests and active links (PRD §4.2, API_SPEC §4)."""
    # Find all businesses user belongs to
    bu_rows = (
        await session.execute(
            select(BusinessUser.business_id).where(BusinessUser.user_id == user_id)
        )
    ).scalars().all()

    if not bu_rows:
        return {"success": True, "data": []}

    links = (
        await session.execute(
            select(CaClientLink).where(CaClientLink.business_id.in_(bu_rows))
        )
    ).scalars().all()

    result = []
    for link in links:
        firm = await session.get(CaFirm, link.ca_firm_id) if link.ca_firm_id else None
        result.append({
            "id": str(link.id),
            "ca_firm_id": str(link.ca_firm_id) if link.ca_firm_id else None,
            "firm_name": firm.firm_name if firm else None,
            "business_id": str(link.business_id),
            "status": link.status.value,
            "initiated_by": link.initiated_by.value,
            "invite_code": link.invite_code,
            "consent_record_id": str(link.consent_record_id) if link.consent_record_id else None,
            "requested_at": link.requested_at.isoformat() if link.requested_at else None,
            "responded_at": link.responded_at.isoformat() if link.responded_at else None,
            "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
        })

    return {"success": True, "data": result}


@router.post("/invite-code")
async def generate_invite_code_endpoint(
    body: InviteCodeIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
) -> dict[str, Any]:
    """Flow B: Generate 7-day single-use invite code."""
    info = await generate_invite_code(session, user_id, body.business_id)
    return {
        "success": True,
        "data": {
            "id": info.id,
            "invite_code": info.invite_code,
            "expires_at": info.expires_at.isoformat(),
        },
    }


@router.post("/{link_id}/accept")
async def accept_link_endpoint(
    link_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
    body: ConsentAcceptIn | None = None,
) -> dict[str, Any]:
    """Client accepts pending firm link request with versioned consent."""
    version = body.consent_text_version if body else "v1.0"
    link = await accept_consent(session, link_id, actor_user_id=user_id, consent_version=version)
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "status": link.status.value,
            "consent_record_id": str(link.consent_record_id),
            "consent_text_version": version,
        },
    }


@router.post("/{link_id}/reject")
async def reject_link_endpoint(
    link_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
) -> dict[str, Any]:
    """Client rejects pending firm link request."""
    link = await reject_consent(session, link_id, actor_user_id=user_id)
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "status": link.status.value,
        },
    }


@router.post("/{link_id}/revoke")
async def revoke_link_endpoint(
    link_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
    body: ConsentRevokeIn | None = None,
) -> dict[str, Any]:
    """Client revokes access: instant access death."""
    link = await revoke_consent(session, link_id, actor_user_id=user_id)
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "status": link.status.value,
            "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
        },
    }


# Convenience aliases supporting both route structures:
@router.post("/firm/clients/request")
async def request_alias(
    body: FirmRequestIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
) -> dict[str, Any]:
    from app.db.models.core import CaFirmMember

    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        from app.api.errors import ServiceError
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    link = await create_firm_request(
        session, member.firm_id, body.get_gstin(), actor_user_id=user_id
    )
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "ca_firm_id": str(link.ca_firm_id),
            "business_id": str(link.business_id),
            "status": link.status.value,
            "requested_at": link.requested_at.isoformat() if link.requested_at else None,
        },
    }


@router.post("/redeem")
async def redeem_alias(
    body: RedeemIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Depends(require_user)],
) -> dict[str, Any]:
    from app.db.models.core import CaFirmMember

    member = (
        await session.execute(
            select(CaFirmMember).where(CaFirmMember.user_id == user_id)
        )
    ).scalars().first()
    if not member:
        from app.api.errors import ServiceError
        raise ServiceError("not a firm member", 403, "FORBIDDEN")

    link = await redeem_invite_code(
        session, member.firm_id, body.invite_code, actor_user_id=user_id
    )
    return {
        "success": True,
        "data": {
            "id": str(link.id),
            "ca_firm_id": str(link.ca_firm_id),
            "business_id": str(link.business_id),
            "status": link.status.value,
            "consent_record_id": str(link.consent_record_id),
        },
    }
