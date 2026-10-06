from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ServiceError
from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_user
from app.db.models.gst import Invoice
from app.db.session import get_session
from app.services import irp_service

router = APIRouter(tags=["einvoice"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

@router.post("/invoices/{invId}/irn")
async def generate_irn(
    invId: uuid.UUID,
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    invoice = await session.get(Invoice, invId)
    if not invoice:
        raise ServiceError("invoice not found", 404, "NOT_FOUND")

    from app.core.access import resolve_gstin_access
    access = await resolve_gstin_access(session, user_id, invoice.gstin)
    access.require_write()

    e_invoice = await irp_service.generate_sandbox_irn(session, invId, user_id)

    return {
        "success": True,
        "data": {
            "irn": e_invoice.irn,
            "ack_no": e_invoice.ack_no,
            "ack_date": e_invoice.ack_date,
        }
    }

@router.post("/einvoices/{irnId}/cancel")
async def cancel_irn(
    irnId: uuid.UUID,
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    invoice = await session.get(Invoice, irnId)
    if not invoice:
        raise ServiceError("invoice not found", 404, "NOT_FOUND")

    from app.core.access import resolve_gstin_access
    access = await resolve_gstin_access(session, user_id, invoice.gstin)
    access.require_write()

    e_invoice = await irp_service.cancel_sandbox_irn(session, irnId, user_id)

    return {
        "success": True,
        "data": {
            "irn": e_invoice.irn,
            "cancelled_at": e_invoice.cancelled_at.isoformat() if e_invoice.cancelled_at else None,
        }
    }

@router.get("/gst-accounts/{gstin}/months/{fp}/einvoices")
async def get_einvoices(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
    einvoices = await irp_service.get_einvoices(session, access.gstin, fp)
    return {
        "success": True,
        "data": [
            {
                "irn": e.irn,
                "ack_no": e.ack_no,
                "ack_date": e.ack_date,
                "cancelled_at": e.cancelled_at,
            }
            for e in einvoices
        ]
    }
