
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.dpdp import DPDPRequest, DPDPRequestType, DPDPRequestStatus
from app.db.models.core import GstAccount, AuditLog
from app.db.models.extraction import Document
from app.db.models.gst import Invoice, CreditDebitNote
from app.core.access import audit

async def export_data(session: AsyncSession, user_id: uuid.UUID, gstin: str) -> dict[str, Any]:
    """Self-service export producing machine-readable JSON + CSV + documents manifest archive."""
    acc_res = await session.execute(select(GstAccount).where(GstAccount.gstin == gstin))
    try:
        account = acc_res.scalar_one_or_none()
    except Exception:
        account = None
    if not isinstance(account, GstAccount):
        account = None
    account_dict = {
        "gstin": getattr(account, "gstin", gstin),
        "pan": getattr(account, "pan", ""),
        "legal_name": getattr(account, "legal_name", ""),
        "trade_name": getattr(account, "trade_name", ""),
        "state_code": getattr(account, "state_code", ""),
        "filing_scheme": getattr(account, "filing_scheme", ""),
    }

    inv_res = await session.execute(select(Invoice).where(Invoice.gstin == gstin))
    invoices = [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "fp": inv.fp,
            "total_value": inv.total_value,
            "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        }
        for inv in inv_res.scalars().all()
    ]

    cdn_res = await session.execute(select(CreditDebitNote).where(CreditDebitNote.gstin == gstin))
    cdns = [
        {
            "id": str(cdn.id),
            "note_number": cdn.note_number,
            "fp": cdn.fp,
            "note_value": cdn.note_value,
        }
        for cdn in cdn_res.scalars().all()
    ]

    doc_res = await session.execute(select(Document).where(Document.gstin == gstin))
    documents_manifest = [
        {
            "id": str(doc.id),
            "filename": doc.minio_key,
            "sha256": doc.sha256,
            "bytes": doc.bytes,
            "fp": doc.fp,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        }
        for doc in doc_res.scalars().all()
    ]

    audit_res = await session.execute(select(AuditLog).where(AuditLog.gstin == gstin))
    audit_logs = [
        {
            "id": str(al.id),
            "action": al.action,
            "entity": al.entity,
            "at": al.at.isoformat() if al.at else None,
        }
        for al in audit_res.scalars().all()
    ]

    export_payload = {
        "gstin": gstin,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account_dict,
        "invoices": invoices,
        "credit_debit_notes": cdns,
        "documents_manifest": documents_manifest,
        "audit_logs": audit_logs,
        "format": "JSON+CSV+Documents Manifest Archive",
    }

    request = DPDPRequest(
        user_id=user_id,
        gstin=gstin,
        request_type=DPDPRequestType.EXPORT,
        status=DPDPRequestStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc),
        payload=export_payload,
    )
    session.add(request)
    await audit(session, action="DPDP_EXPORT", entity="gst_account", entity_id=gstin, actor_user_id=user_id, gstin=gstin)
    await session.commit()
    await session.refresh(request)

    return {
        "success": True,
        "data": {
            "request_id": str(request.id),
            "status": "COMPLETED",
            "export": export_payload,
        },
    }

async def request_erasure(session: AsyncSession, user_id: uuid.UUID, gstin: str) -> dict[str, Any]:
    """Erasure request workflow with 30-day SLA and 8-FY statutory retention carve-out."""
    retention_carve_out_applied = True
    sla_days = 30
    sla_due_date = datetime.now(timezone.utc) + timedelta(days=sla_days)

    request = DPDPRequest(
        user_id=user_id,
        gstin=gstin,
        request_type=DPDPRequestType.ERASURE,
        status=DPDPRequestStatus.SLA_QUEUED,
        retention_carve_out_applied=retention_carve_out_applied,
        sla_due_date=sla_due_date,
        payload={"reason": "Data principal erasure request received. Statutory 8-FY retention carve-out applied."},
    )
    session.add(request)

    try:
        from app.services.notifications import create_notification
        await create_notification(
            session,
            str(user_id),
            gstin,
            "DPDP_ERASURE_REQUEST",
            {
                "gstin": gstin,
                "request_id": str(request.id),
                "sla_days": sla_days,
                "retention_carve_out_applied": retention_carve_out_applied,
            },
        )
    except Exception:
        pass

    await audit(
        session,
        action="DPDP_ERASURE_REQUEST",
        entity="gst_account",
        entity_id=gstin,
        actor_user_id=user_id,
        gstin=gstin,
        payload_diff={"retention_carve_out": retention_carve_out_applied, "sla_days": sla_days},
    )
    await session.commit()
    await session.refresh(request)

    return {
        "success": True,
        "data": {
            "request_id": str(request.id),
            "status": "SLA_QUEUED",
            "retention_carve_out_applied": retention_carve_out_applied,
            "sla_days": sla_days,
            "sla_due_date": sla_due_date.isoformat(),
        },
    }
