from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.api.errors import ServiceError
from app.db.models.core import GstAccount
from app.db.models.gst import EInvoice, Invoice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def generate_sandbox_irn(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EInvoice:
    # 1. Fetch invoice
    result = await session.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise ServiceError("invoice not found", 404, "NOT_FOUND")

    # 2. Check gate (irn_applicable)
    acc_res = await session.execute(
        select(GstAccount).where(GstAccount.gstin == invoice.gstin)
    )
    account = acc_res.scalar_one()
    if not account.irn_applicable:
        raise ServiceError("IRN not applicable for this GSTIN", 400, "INVALID_OPERATION")

    # 3. Check for existing EInvoice
    existing = await session.execute(
        select(EInvoice).where(EInvoice.invoice_id == invoice_id)
    )
    e_invoice = existing.scalar_one_or_none()
    if e_invoice:
        return e_invoice  # Already generated

    # 4. Generate mock IRN
    # In sandbox, just create one
    mock_irn = f"MOCK-IRN-{uuid.uuid4().hex[:32].upper()}"

    new_e_invoice = EInvoice(
        invoice_id=invoice_id,
        irn=mock_irn,
        ack_no=f"ACK-{uuid.uuid4().hex[:10].upper()}",
        ack_date=datetime.now(UTC),
        signed_qr_base64="dGhpcy1pcy1hLW1vY2stcXItY29kZQ==",  # this-is-a-mock-qr-code
        cancel_window_until=datetime.now(UTC) + timedelta(hours=24)
    )

    session.add(new_e_invoice)
    await session.commit()
    await session.refresh(new_e_invoice)

    return new_e_invoice


async def cancel_sandbox_irn(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EInvoice:
    result = await session.execute(
        select(EInvoice).where(EInvoice.invoice_id == invoice_id)
    )
    e_invoice = result.scalar_one_or_none()
    if not e_invoice:
        raise ServiceError("e-invoice not found", 404, "NOT_FOUND")

    if e_invoice.cancelled_at:
        raise ServiceError("e-invoice already cancelled", 400, "INVALID_OPERATION")

    if e_invoice.cancel_window_until and datetime.now(UTC) > e_invoice.cancel_window_until:
        raise ServiceError("Cancellation window expired (24h limit)", 400, "INVALID_OPERATION")

    e_invoice.cancelled_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(e_invoice)
    return e_invoice


async def get_einvoices(
    session: AsyncSession,
    gstin: str,
    fp: str,
) -> list[EInvoice]:
    result = await session.execute(
        select(EInvoice)
        .join(Invoice, EInvoice.invoice_id == Invoice.id)
        .where(Invoice.gstin == gstin)
        .where(Invoice.fp == fp)
    )
    return list(result.scalars().all())

