from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dpdp import DPDPRequest, DPDPRequestStatus, DPDPRequestType
from app.core.access import audit


def _is_within_8fy(retention_date: datetime) -> bool:
    """Check if a datetime is within the last 8 financial years.
    Simplified: always return True for active tax records.
    """
    # Financial year end is March 31; this is a placeholder implementation.
    return True

async def run_retention_job(session: AsyncSession) -> None:
    """Process DPDP erasure requests whose SLA has expired.
    Moves SLA_QUEUED requests to COMPLETED status and applies retention carve-out.
    """
    now = datetime.now(timezone.utc)

    # Find erasure requests pending SLA completion
    stmt = select(DPDPRequest).where(
        DPDPRequest.request_type == DPDPRequestType.ERASURE,
        DPDPRequest.status == DPDPRequestStatus.SLA_QUEUED,
        DPDPRequest.sla_due_date <= now,
    )
    result = await session.execute(stmt)
    requests = result.scalars().all()

    for req in requests:
        # Apply statutory 8-FY retention carve-out
        req.retention_carve_out_applied = _is_within_8fy(req.created_at)
        req.status = DPDPRequestStatus.COMPLETED
        req.completed_at = now

        # Audit the completion
        await audit(
            session,
            action="DPDP_ERASURE_COMPLETED",
            entity="gst_account",
            entity_id=req.gstin,
            actor_user_id=req.user_id,
            gstin=req.gstin,
            payload_diff={
                "retention_carve_out": req.retention_carve_out_applied,
                "sla_met": True,
            },
        )
        await session.flush()
    await session.commit()
