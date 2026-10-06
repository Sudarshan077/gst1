"""DPDP data-principal services: self-service export + erasure workflow.

Implementation targets SECURITY_AND_ACCESS.md §4:
  - Export returns machine-readable JSON + CSV + documents manifest.
  - Erasure queues a 30-day SLA request with the 8-FY statutory retention
    carve-out applied.
  - Both actions write append-only audit rows.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.access import audit
from app.db.models.core import AuditLog, GstAccount
from app.db.models.dpdp import DPDPRequest, DPDPRequestStatus, DPDPRequestType
from app.db.models.extraction import Document
from app.db.models.gst import CreditDebitNote, Invoice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def export_data(
    session: AsyncSession, user_id: uuid.UUID, gstin: str
) -> dict[str, Any]:
    """Self-service export producing machine-readable JSON + CSV + documents manifest archive."""
    account = (
        await session.execute(
            select(GstAccount).where(GstAccount.gstin == gstin)
        )
    ).scalar_one_or_none()

    account_dict: dict[str, Any] = {
        "gstin": account.gstin if account else gstin,
        "pan": account.pan if account else "",
        "legal_name": account.legal_name if account else "",
        "trade_name": account.trade_name if account else "",
        "state_code": account.state_code if account else "",
        "filing_scheme": (
            account.filing_scheme.value if account else ""
        ),
    }

    invoices = (
        await session.execute(select(Invoice).where(Invoice.gstin == gstin))
    ).scalars().all()
    invoice_rows = [
        {
            "id": str(inv.id),
            "invoice_no": inv.invoice_no,
            "fp": inv.fp,
            "total_value_paise": inv.total_value_minor,
            "status": inv.status.value,
        }
        for inv in invoices
    ]

    cdns = (
        await session.execute(
            select(CreditDebitNote).where(CreditDebitNote.gstin == gstin)
        )
    ).scalars().all()
    cdn_rows = [
        {
            "id": str(cdn.id),
            "note_no": cdn.note_no,
            "fp": cdn.fp,
            "taxable_value_paise": cdn.taxable_value_minor,
        }
        for cdn in cdns
    ]

    docs = (
        await session.execute(
            select(Document).where(Document.gstin == gstin)
        )
    ).scalars().all()
    documents_manifest = [
        {
            "id": str(doc.id),
            "minio_key": doc.minio_key,
            "sha256": doc.sha256,
            "bytes": doc.bytes,
            "fp": doc.fp,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        }
        for doc in docs
    ]

    audit_rows = (
        await session.execute(
            select(AuditLog).where(AuditLog.gstin == gstin)
        )
    ).scalars().all()
    audit_logs = [
        {
            "id": str(al.id),
            "action": al.action,
            "entity": al.entity,
            "at": al.at.isoformat() if al.at else None,
        }
        for al in audit_rows
    ]

    export_payload = {
        "gstin": gstin,
        "exported_at": datetime.now(UTC).isoformat(),
        "account": account_dict,
        "invoices": invoice_rows,
        "credit_debit_notes": cdn_rows,
        "documents_manifest": documents_manifest,
        "audit_logs": audit_logs,
        "format": "JSON+CSV+Documents Manifest Archive",
        "csv_manifest": _to_csv(
            ["id", "minio_key", "sha256", "bytes", "fp", "uploaded_at"],
            documents_manifest,
        ),
    }

    request = DPDPRequest(
        user_id=user_id,
        gstin=gstin,
        request_type=DPDPRequestType.EXPORT,
        status=DPDPRequestStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        payload=export_payload,
    )
    session.add(request)
    await audit(
        session,
        action="DPDP_EXPORT",
        entity="gst_account",
        entity_id=gstin,
        actor_user_id=user_id,
        gstin=gstin,
    )
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


def _to_csv(fields: list[str], rows: list[dict[str, Any]]) -> str:
    """Render a small CSV string for the export archive."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return buf.getvalue()


async def request_erasure(
    session: AsyncSession, user_id: uuid.UUID, gstin: str
) -> dict[str, Any]:
    """Erasure request workflow with 30-day SLA and 8-FY statutory retention carve-out."""
    retention_carve_out_applied = True
    sla_days = 30
    sla_due_date = datetime.now(UTC) + timedelta(days=sla_days)
    reason = (
        "Data principal erasure request received. "
        "Statutory 8-FY retention carve-out applied."
    )

    request = DPDPRequest(
        user_id=user_id,
        gstin=gstin,
        request_type=DPDPRequestType.ERASURE,
        status=DPDPRequestStatus.SLA_QUEUED,
        retention_carve_out_applied=retention_carve_out_applied,
        sla_due_date=sla_due_date,
        payload={"reason": reason},
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
    except Exception as exc:
        logger.warning("DPDP erasure notification failed: %s", exc, exc_info=True)
        # Notification failure must not block the erasure request.

    await audit(
        session,
        action="DPDP_ERASURE_REQUEST",
        entity="gst_account",
        entity_id=gstin,
        actor_user_id=user_id,
        gstin=gstin,
        payload_diff={
            "retention_carve_out": retention_carve_out_applied,
            "sla_days": sla_days,
        },
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
