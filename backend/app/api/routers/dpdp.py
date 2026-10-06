"""DPDP API routes — export + erasure, step-up protected (SECURITY §1/§4).

All GSTIN-scoped routes use require_gstin_access; the /me routes require the
caller to pick a GSTIN from their own account list so no fabricated default
GSTIN is ever used.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_stepup, require_user
from app.db.models.core import GstAccount, UserGstAccess
from app.db.models.dpdp import DPDPRequest
from app.db.session import get_session
from app.services import dpdp_service

router = APIRouter(tags=["dpdp"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StepUpDep = Annotated[uuid.UUID, Depends(require_stepup)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]


@router.post("/gst-accounts/{gstin}/dpdp/export")
async def export(
    gstin: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    _ = access
    return await dpdp_service.export_data(session, user_id, gstin)


@router.post("/gst-accounts/{gstin}/dpdp/erasure")
async def erasure(
    gstin: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    _ = access
    return await dpdp_service.request_erasure(session, user_id, gstin)


@router.post("/me/data/export")
async def me_data_export(
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Export for the caller's first accessible GSTIN (no fabricated default)."""
    gstin = await _first_gstin(session, user_id)
    return await dpdp_service.export_data(session, user_id, gstin)


@router.post("/me/data/erasure-request")
async def me_data_erasure(
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Erasure request for the caller's first accessible GSTIN."""
    gstin = await _first_gstin(session, user_id)
    return await dpdp_service.request_erasure(session, user_id, gstin)


@router.get("/me/data/export/{request_id}")
async def me_data_export_status(
    request_id: str,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Export job not found") from exc
    req = await session.get(DPDPRequest, rid)
    if not req or req.user_id != user_id:
        raise HTTPException(status_code=404, detail="Export job not found")
    return {
        "success": True,
        "data": {
            "request_id": str(req.id),
            "status": req.status.value,
            "export": req.payload,
        },
    }


async def _first_gstin(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Return the user's first accessible GSTIN; 404 if none exists."""
    row = (
        await session.execute(
            select(GstAccount.gstin)
            .join(UserGstAccess, UserGstAccess.gstin == GstAccount.gstin)
            .where(UserGstAccess.user_id == user_id)
            .order_by(UserGstAccess.granted_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No GSTIN associated with this user")
    return row
