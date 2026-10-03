from __future__ import annotations
import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.dpdp import DPDPRequest, DPDPRequestType, DPDPRequestStatus
from app.api.errors import ServiceError

async def export_data(session: AsyncSession, user_id: uuid.UUID, gstin: str) -> dict[str, Any]:
    # Implementation for export
    request = DPDPRequest(user_id=user_id, gstin=gstin, request_type=DPDPRequestType.EXPORT)
    session.add(request)
    await session.commit()
    return {"success": True, "data": {"request_id": str(request.id), "status": "PENDING"}}

async def request_erasure(session: AsyncSession, user_id: uuid.UUID, gstin: str) -> dict[str, Any]:
    # Implementation for erasure request
    # Need to check 8-FY retention rule
    request = DPDPRequest(user_id=user_id, gstin=gstin, request_type=DPDPRequestType.ERASURE)
    session.add(request)
    await session.commit()
    return {"success": True, "data": {"request_id": str(request.id), "status": "PENDING"}}
