from __future__ import annotations

import uuid
from typing import Any

from app.api.errors import ServiceError
from app.db.models.gst import (
    AmendmentStatus,
    FilingPeriod,
    FilingStatus,
    Gstr1aAmendment,
    Gstr1Export,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def create_gstr1a_amendments(
    session: AsyncSession,
    gstin: str,
    fp: str,
    body: dict[str, Any],
) -> list[dict[str, Any]]:
    # 1. Check filing period is FILED
    period = await session.get(FilingPeriod, (gstin, fp))
    if period is None or period.status != FilingStatus.FILED:
        raise ServiceError(
            "GSTR-1A amendments require a filed return period", 422, "PERIOD_NOT_FILED"
        )

    # 2. Find latest Gstr1Export for gstin & fp
    export_result = await session.execute(
        select(Gstr1Export)
        .where(Gstr1Export.gstin == gstin, Gstr1Export.fp == fp)
        .order_by(Gstr1Export.generated_at.desc())
        .limit(1)
    )
    latest_export = export_result.scalar_one_or_none()
    if latest_export is None:
        raise ServiceError("No Gstr1 export found to amend", 404, "EXPORT_NOT_FOUND")

    amendments_data = body.get("amendments", [])
    created_amendments = []

    for item in amendments_data:
        invoice_id_str = item.get("invoice_id")
        cdn_id_str = item.get("cdn_id")
        field_deltas = item.get("field_deltas", {})
        reason = item.get("reason", "Amendment")

        invoice_id = uuid.UUID(invoice_id_str) if invoice_id_str else None
        cdn_id = uuid.UUID(cdn_id_str) if cdn_id_str else None

        amendment = Gstr1aAmendment(
            target_export_id=latest_export.id,
            invoice_id=invoice_id,
            cdn_id=cdn_id,
            field_deltas=field_deltas,
            reason=reason,
            status=AmendmentStatus.DRAFT,
        )
        session.add(amendment)
        created_amendments.append(amendment)

    await session.commit()

    return [
        {
            "id": str(a.id),
            "target_export_id": str(a.target_export_id),
            "status": a.status,
            "reason": a.reason,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in created_amendments
    ]
