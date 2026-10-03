from __future__ import annotations

import uuid
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_user, require_stepup
from app.db.session import get_session
from app.services import dpdp_service
from app.db.models.dpdp import DPDPRequest

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
    return await dpdp_service.export_data(session, user_id, gstin)

@router.post("/gst-accounts/{gstin}/dpdp/erasure")
async def erasure(
    gstin: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    return await dpdp_service.request_erasure(session, user_id, gstin)

@router.post("/me/data/export")
async def me_data_export(
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    # Default to user's default gstin or demo gstin if none specified
    gstin = "29AAAAA0000A1Z5"
    return await dpdp_service.export_data(session, user_id, gstin)

@router.get("/me/data/export/{request_id}")
async def me_data_export_status(
    request_id: str,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    req = await session.get(DPDPRequest, uuid.UUID(request_id))
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

@router.post("/me/data/erasure-request")
async def me_data_erasure(
    user_id: StepUpDep,
    session: SessionDep,
) -> dict[str, Any]:
    gstin = "29AAAAA0000A1Z5"
    return await dpdp_service.request_erasure(session, user_id, gstin)
