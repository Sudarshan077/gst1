"""Deadline engine & reminders: computes due dates (GSTR-1, IFF, 3B, 2B, CMP-08, GSTR-4)
based on filing scheme and state code, manages filing periods, and fires reminders.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.gst import (
    FilingPeriod,
    FilingStatus,
    Invoice,
    Notification,
)
from app.db.models.extraction import Document
from app.db.models.core import GstAccount, UserGstAccess
from app.api.errors import ServiceError

# Category 1 States / UTs for QRMP GSTR-3B (due 22nd of month succeeding quarter)
CATEGORY_1_STATES = {
    "22",  # Chhattisgarh
    "23",  # Madhya Pradesh
    "24",  # Gujarat
    "26",  # Dadra and Nagar Haveli and Daman and Diu
    "27",  # Maharashtra
    "28",  # Andhra Pradesh
    "29",  # Karnataka
    "30",  # Goa
    "31",  # Lakshadweep
    "32",  # Kerala
    "33",  # Tamil Nadu
    "34",  # Puducherry
    "35",  # Andaman and Nicobar Islands
    "36",  # Telangana
    "37",  # Ladakh
}


def compute_due_dates(gstin: str, fp: str, scheme: str) -> dict[str, Any]:
    if len(fp) != 6 or not fp.isdigit():
        raise ValueError("Invalid fp format, expected MMYYYY")
    m = int(fp[:2])
    y = int(fp[2:])
    if not (1 <= m <= 12):
        raise ValueError("Invalid month in fp")
    state_code = gstin[:2].upper()

    def next_month(month: int, year: int) -> tuple[int, int]:
        if month == 12:
            return 1, year + 1
        return month + 1, year

    def quarter_end_month(month: int) -> int:
        return ((month - 1) // 3 + 1) * 3

    nm, ny = next_month(m, y)
    gstr2b_due = date(ny, nm, 14)

    if scheme == "COMPOSITION":
        q_end = quarter_end_month(m)
        qm, qy = next_month(q_end, y)
        cmp08_due = date(qy, qm, 18)
        gstr4_due = date(y, 4, 30) if m == 3 else None
        return {
            "gstr1_due_date": None,
            "gstr3b_due_date": None,
            "gstr2b_due_date": gstr2b_due,
            "cmp08_due_date": cmp08_due,
            "gstr4_due_date": gstr4_due,
            "iff_eligible": False,
        }

    if scheme == "QRMP":
        q_end = quarter_end_month(m)
        is_quarter_end = (m == q_end)
        iff_eligible = not is_quarter_end

        gstr1_m, gstr1_y = next_month(m, y)
        gstr1_due = date(gstr1_y, gstr1_m, 13)
        iff_due = date(gstr1_y, gstr1_m, 13) if iff_eligible else None

        qm, qy = next_month(q_end, y)
        day_3b = 22 if state_code in CATEGORY_1_STATES else 24
        gstr3b_due = date(qy, qm, day_3b)

        return {
            "gstr1_due_date": gstr1_due,
            "gstr3b_due_date": gstr3b_due,
            "gstr2b_due_date": gstr2b_due,
            "iff_due_date": iff_due,
            "iff_eligible": iff_eligible,
        }

    else:
        # REGULAR_MONTHLY
        gstr1_m, gstr1_y = next_month(m, y)
        gstr1_due = date(gstr1_y, gstr1_m, 11)
        gstr3b_m, gstr3b_y = next_month(m, y)
        gstr3b_due = date(gstr3b_y, gstr3b_m, 20)
        return {
            "gstr1_due_date": gstr1_due,
            "gstr3b_due_date": gstr3b_due,
            "gstr2b_due_date": gstr2b_due,
            "iff_eligible": False,
        }


async def get_or_create_period(
    session: AsyncSession, gstin: str, fp: str, scheme: str
) -> FilingPeriod:
    period = await session.get(FilingPeriod, (gstin, fp))
    if period is None:
        dates = compute_due_dates(gstin, fp, scheme)
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot=scheme,
            status=FilingStatus.OPEN,
            gstr1_due_date=dates.get("gstr1_due_date"),
            gstr3b_due_date=dates.get("gstr3b_due_date"),
            iff_eligible=dates.get("iff_eligible", False),
            nil_return=False,
        )
        session.add(period)
        await session.flush()
    return period


async def list_periods_for_fy(
    session: AsyncSession, gstin: str, fy: str | None = None
) -> list[dict[str, Any]]:
    account = await session.get(GstAccount, gstin)
    if account is None:
        raise ServiceError("GST account not found", 404, "GSTIN_NOT_FOUND")

    # Determine list of fps for FY
    # FY format e.g. "2025-26" or "2025"
    if not fy:
        today = date.today()
        yr = today.year
        if today.month < 4:
            yr -= 1
        fy = f"{yr}-{str(yr+1)[2:]}"

    # Parse starting year from fy (e.g. "2025-26" -> 2025)
    start_yr = int(fy.split("-")[0])
    # 12 periods: April (04) to March (03) of start_yr + 1
    fps = []
    for m in range(4, 13):
        fps.append(f"{m:02d}{start_yr}")
    for m in range(1, 4):
        fps.append(f"{m:02d}{start_yr + 1}")

    result_periods = []
    for fp in fps:
        period = await get_or_create_period(session, gstin, fp, account.filing_scheme.value)
        result_periods.append(_period_out(period))

    await session.commit()
    return result_periods


async def get_month_summary(
    session: AsyncSession, gstin: str, fp: str
) -> dict[str, Any]:
    account = await session.get(GstAccount, gstin)
    if account is None:
        raise ServiceError("GST account not found", 404, "GSTIN_NOT_FOUND")

    period = await get_or_create_period(session, gstin, fp, account.filing_scheme.value)

    # Document counts
    doc_total = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.gstin == gstin, Document.fp == fp)
        )
    ).scalar_one()

    # Invoice ledger totals for SALES in this period
    invoices_result = await session.execute(
        select(Invoice).where(
            Invoice.gstin == gstin,
            Invoice.fp == fp,
            Invoice.direction == "SALES",
            Invoice.status != "DRAFT",
        )
    )
    invoices = invoices_result.scalars().all()

    taxable_minor = 0
    cgst_minor = 0
    sgst_minor = 0
    igst_minor = 0
    cess_minor = 0
    total_val_minor = 0

    for inv in invoices:
        total_val_minor += inv.total_value_minor
        for line in inv.lines:
            taxable_minor += line.taxable_value_minor
            cgst_minor += line.cgst_minor
            sgst_minor += line.sgst_minor
            igst_minor += line.igst_minor
            cess_minor += line.cess_minor

    today = date.today()
    days_to_gstr1 = (
        (period.gstr1_due_date - today).days if period.gstr1_due_date else None
    )
    days_to_gstr3b = (
        (period.gstr3b_due_date - today).days if period.gstr3b_due_date else None
    )

    return {
        "gstin": gstin,
        "fp": fp,
        "status": period.status.value,
        "nil_return": period.nil_return,
        "gstr1_due_date": period.gstr1_due_date.isoformat() if period.gstr1_due_date else None,
        "gstr3b_due_date": period.gstr3b_due_date.isoformat() if period.gstr3b_due_date else None,
        "days_to_gstr1_deadline": days_to_gstr1,
        "days_to_gstr3b_deadline": days_to_gstr3b,
        "document_counts": {
            "total": doc_total,
        },
        "ledger_totals": {
            "taxable_value_minor": taxable_minor,
            "cgst_minor": cgst_minor,
            "sgst_minor": sgst_minor,
            "igst_minor": igst_minor,
            "cess_minor": cess_minor,
            "total_value_minor": total_val_minor,
        },
    }


async def check_and_fire_reminders(session: AsyncSession) -> int:
    """Evaluate open filing periods and create notifications if deadlines are within 7 days."""
    today = date.today()
    # Find all open periods with due dates in the future or within 7 days
    query = select(FilingPeriod).where(FilingPeriod.status == FilingStatus.OPEN)
    periods = (await session.execute(query)).scalars().all()

    fired_count = 0
    for period in periods:
        due_dates = [
            ("GSTR-1", period.gstr1_due_date),
            ("GSTR-3B", period.gstr3b_due_date),
            ("IFF", period.iff_due_date),
            ("CMP-08", period.cmp08_due_date),
            ("GSTR-4", period.gstr4_due_date),
        ]
        for return_type, due_date in due_dates:
            if due_date is None:
                continue
            days_left = (due_date - today).days
            if 0 <= days_left <= 7:
                # Find users with access to this GSTIN
                access_rows = (
                    await session.execute(
                        select(UserGstAccess).where(UserGstAccess.gstin == period.gstin)
                    )
                ).scalars().all()

                for acc in access_rows:
                    # Check if notification already sent today for this return type and fp
                    existing_notif = (
                        await session.execute(
                            select(Notification).where(
                                Notification.user_id == acc.user_id,
                                Notification.gstin == period.gstin,
                                Notification.type == "DEADLINE_REMINDER",
                                Notification.payload["fp"].as_string() == period.fp,
                                Notification.payload["return_type"].as_string() == return_type,
                                func.date(Notification.created_at) == today,
                            )
                        )
                    ).scalar_one_or_none()

                    if existing_notif is None:
                        from app.services.notifications import create_notification
                        await create_notification(
                            session,
                            str(acc.user_id),
                            period.gstin,
                            "DEADLINE_REMINDER",
                            {
                                "fp": period.fp,
                                "return_type": return_type,
                                "due_date": due_date.isoformat(),
                                "days_remaining": days_left,
                            },
                        )
                        fired_count += 1
    await session.commit()
    return fired_count


def _period_out(period: FilingPeriod) -> dict[str, Any]:
    return {
        "gstin": period.gstin,
        "fp": period.fp,
        "scheme_snapshot": period.scheme_snapshot,
        "status": period.status.value,
        "gstr1_due_date": period.gstr1_due_date.isoformat() if period.gstr1_due_date else None,
        "gstr3b_due_date": period.gstr3b_due_date.isoformat() if period.gstr3b_due_date else None,
        "iff_eligible": period.iff_eligible,
        "nil_return": period.nil_return,
        "locked_at": period.locked_at.isoformat() if period.locked_at else None,
        "filed_at": period.filed_at.isoformat() if period.filed_at else None,
    }
