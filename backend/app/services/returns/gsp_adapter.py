from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.core.access import audit
from app.db.models.gst import FilingPeriod, FilingStatus, Gstr2bEntry, Gstr2bSource, Gstr2bStatement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def file_gstr1_gsp(
    session: AsyncSession,
    gstin: str,
    fp: str,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    period = await session.get(FilingPeriod, (gstin, fp))

    ref_id = f"GSP-GSTR1-{uuid.uuid4().hex[:12].upper()}"
    ack_no = f"ACK-G1-{uuid.uuid4().hex[:10].upper()}"

    if period is None:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="REGULAR_MONTHLY",
            status=FilingStatus.FILED,
            filed_at=datetime.now(UTC),
            filed_by=user_id,
        )
        session.add(period)
    else:
        period.status = FilingStatus.FILED
        period.filed_at = datetime.now(UTC)
        period.filed_by = user_id

    await audit(
        session,
        action="GSP_FILE_GSTR1",
        entity="return",
        entity_id=f"{gstin}-{fp}",
        actor_user_id=user_id,
        gstin=gstin,
    )
    await session.commit()

    return {
        "success": True,
        "ref_id": ref_id,
        "ack_no": ack_no,
        "status": "FILED",
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def file_gstr3b_gsp(
    session: AsyncSession,
    gstin: str,
    fp: str,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    period = await session.get(FilingPeriod, (gstin, fp))

    ref_id = f"GSP-GSTR3B-{uuid.uuid4().hex[:12].upper()}"
    ack_no = f"ACK-3B-{uuid.uuid4().hex[:10].upper()}"

    if period is None:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="REGULAR_MONTHLY",
            status=FilingStatus.FILED,
            filed_at=datetime.now(UTC),
            filed_by=user_id,
        )
        session.add(period)
    else:
        period.status = FilingStatus.FILED
        period.filed_at = datetime.now(UTC)
        period.filed_by = user_id

    await audit(
        session,
        action="GSP_FILE_GSTR3B",
        entity="return",
        entity_id=f"{gstin}-{fp}",
        actor_user_id=user_id,
        gstin=gstin,
    )
    await session.commit()

    return {
        "success": True,
        "ref_id": ref_id,
        "ack_no": ack_no,
        "status": "FILED",
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def fetch_gstr2b_gsp(
    session: AsyncSession,
    gstin: str,
    fp: str,
    user_id: uuid.UUID,
) -> Gstr2bStatement:
    existing = await session.execute(
        select(Gstr2bStatement).where(
            Gstr2bStatement.gstin == gstin,
            Gstr2bStatement.fp == fp,
        )
    )
    stmt = existing.scalar_one_or_none()
    if stmt:
        return stmt

    raw_key = f"gstr2b/{gstin}/{fp}/gsp_{uuid.uuid4()}.json"
    statement = Gstr2bStatement(
        gstin=gstin,
        fp=fp,
        source=Gstr2bSource.GSP_API,
        raw_minio_key=raw_key,
        imported_by=user_id,
    )
    session.add(statement)
    await session.flush()

    sample_entry = Gstr2bEntry(
        statement_id=statement.id,
        supplier_gstin="29ABCDE1234F1Z5",
        invoice_no="GSP-INV-001",
        invoice_date=date.fromisoformat("2026-09-10"),
        taxable_value_minor=100000,
        cgst_minor=9000,
        sgst_minor=9000,
        igst_minor=0,
        cess_minor=0,
        itc_eligible=True,
        doc_type="INV",
    )
    session.add(sample_entry)

    await audit(
        session,
        action="GSP_FETCH_GSTR2B",
        entity="return",
        entity_id=f"{gstin}-{fp}",
        actor_user_id=user_id,
        gstin=gstin,
    )
    await session.commit()
    await session.refresh(statement)
    return statement
