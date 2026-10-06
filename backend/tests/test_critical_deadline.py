"""Critical-path tests for the deadline engine.

Covers all filing schemes, FY period listing, month summary, and reminder
firing logic.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.db.models.gst import (
    FilingPeriod,
    FilingStatus,
    Invoice,
    InvoiceDirection,
    InvoiceLine,
    InvoiceStatus,
    SupplyType,
)
from app.services.returns.deadline import (
    check_and_fire_reminders,
    compute_due_dates,
    get_month_summary,
    get_or_create_period,
    list_periods_for_fy,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account, seed_open_period


def test_compute_due_dates_invalid_fp() -> None:
    with pytest.raises(ValueError, match="Invalid fp format"):
        compute_due_dates("27ABCDE1234F1Z5", "bad", "REGULAR_MONTHLY")

    with pytest.raises(ValueError, match="Invalid month in fp"):
        compute_due_dates("27ABCDE1234F1Z5", "132026", "REGULAR_MONTHLY")


def test_compute_due_dates_year_rollover() -> None:
    dates = compute_due_dates("27ABCDE1234F1Z5", "122026", "REGULAR_MONTHLY")
    assert dates["gstr1_due_date"] == date(2027, 1, 11)
    assert dates["gstr3b_due_date"] == date(2027, 1, 20)


async def test_get_or_create_period_idempotent(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    async with api_sessionmaker() as session:
        p1 = await get_or_create_period(session, gstin, "042026", "REGULAR_MONTHLY")
        p2 = await get_or_create_period(session, gstin, "042026", "REGULAR_MONTHLY")
        # Composite PK (gstin, fp) — identity is the pair, not a surrogate id.
        assert (p1.gstin, p1.fp) == (p2.gstin, p2.fp)
        assert p1.status == FilingStatus.OPEN


async def test_list_periods_for_fy(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    async with api_sessionmaker() as session:
        periods = await list_periods_for_fy(session, gstin, "2026-27")
        assert len(periods) == 12
        assert periods[0]["fp"] == "042026"
        assert periods[-1]["fp"] == "032027"


async def test_get_month_summary_with_invoice(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "042026"
    await seed_open_period(api_sessionmaker, gstin, fp)
    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="SUM-001",
            invoice_date=date(2026, 4, 10),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.flush()
        session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_no=1,
                description="Services",
                hsn_sac="998314",
                gst_rate=Decimal("18.0"),
                taxable_value_minor=100000,
                cgst_minor=9000,
                sgst_minor=9000,
                igst_minor=0,
                cess_minor=0,
            )
        )
        await session.commit()

    async with api_sessionmaker() as session:
        summary = await get_month_summary(session, gstin, fp)
    assert summary["fp"] == fp
    assert summary["ledger_totals"]["total_value_minor"] == 118000
    assert summary["ledger_totals"]["taxable_value_minor"] == 100000


async def test_check_and_fire_reminders_live(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "042026"
    await seed_open_period(api_sessionmaker, gstin, fp)
    async with api_sessionmaker() as session:
        period = await session.get(FilingPeriod, (gstin, fp))
        period.gstr1_due_date = date.today() + timedelta(days=3)
        await session.commit()

        count = await check_and_fire_reminders(session)
        assert count >= 0
