from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.errors import ServiceError
from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_user
from app.db.models.gst import Invoice, InvoiceDirection, InvoiceStatus
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

@router.get("/gst-accounts/{gstin}/months/{fp}/invoices")
async def get_invoices_for_irn(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
    """Confirmed outward (SALES) invoices eligible for IRN generation.

    The IRN board lists human-readable invoice_no / date / buyer / total instead
    of forcing the CA to paste a database Invoice UUID. Each row still carries
    its Invoice.id so the frontend can POST /invoices/{id}/irn, but the internal
    key is never shown to the user. Includes IRN state (pending / generated /
    cancelled) so already-processed invoices are visibly gated.
    """
    result = await session.execute(
        select(Invoice)
        .options(selectinload(Invoice.e_invoice))
        .where(Invoice.gstin == access.gstin)
        .where(Invoice.fp == fp)
        .where(Invoice.direction == InvoiceDirection.SALES)
        .where(Invoice.status == InvoiceStatus.CONFIRMED)
        .order_by(Invoice.invoice_date.desc(), Invoice.invoice_no.asc())
    )
    invoices = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": str(inv.id),
                "invoice_no": inv.invoice_no,
                "invoice_date": inv.invoice_date.isoformat(),
                "buyer_gstin": inv.buyer_gstin,
                "total_value_minor": inv.total_value_minor,
                "supply_type": inv.supply_type.value,
                "irn": inv.e_invoice.irn if inv.e_invoice else None,
                "irn_status": (
                    "CANCELLED"
                    if inv.e_invoice and inv.e_invoice.cancelled_at
                    else ("GENERATED" if inv.e_invoice else "PENDING")
                ),
            }
            for inv in invoices
        ],
    }
