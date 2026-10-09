"""Task 9.4 — ITC reconciliation report endpoint (PHASE9_QA_SWEEP_FIXES §3.9.4).

The dashboard's data contract: `GET /gst-accounts/{gstin}/months/{fp}/itc/report`
returns the 5-status reconciliation rows enriched with BOTH sides' figures,
the per-status counts, and the GSTR-3B ITC prefill totals — all in integer
paise, all behind the GSTIN access guard.

Synthetic fixtures only; every GSTIN comes from `make_gstin()` (mod-36).
"""

from datetime import date
from decimal import Decimal

import pytest
from app.db.models.gst import (
    Invoice,
    InvoiceDirection,
    InvoiceLine,
    InvoiceStatus,
    SupplyType,
)
from httpx import AsyncClient

from tests.auth_helpers import make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin

FP = "102026"

# Distinct enough that difflib never fuzzy-matches them across rows (the
# engine's fuzzy PROBABLE path fires above 0.8 SequenceMatcher ratio).
INV_MATCHED = "ITC-A1-MATCH"
INV_PROBABLE = "ITC-B2-PROBABL"
INV_UNMATCHED = "ITC-C3-UNMATCH"
INV_BOOKS_ONLY = "ITC-D4-BOOKSONLY"
INV_2B_ONLY = "ITC-E5-2BONLY"
# The 2B statement spells the PROBABLE invoice correctly; the books row has
# the typo. Same supplier, same amount -> the engine's fuzzy path (ratio
# 0.97 > 0.8) classifies it PROBABLE.
INV_PROBABLE_2B = "ITC-B2-PROBABLE"


async def _seed_period_with_books(client: AsyncClient, api_sessionmaker) -> tuple[str, dict]:
    """Register a user, attach a GSTIN, seed the four purchase invoices."""
    mobile = make_mobile()
    auth_data = await register_and_login(client, mobile)
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()
    supplier = make_gstin(state_code="29")

    created = await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={"gstin": gstin, "legal_name": "ITC Report Co"},
    )
    assert created.status_code == 200, created.text

    async with api_sessionmaker() as session:
        inv_matched = Invoice(
            gstin=gstin,
            fp=FP,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier,
            invoice_no=INV_MATCHED,
            invoice_date=date(2026, 10, 1),
            place_of_supply="29",
            supply_type=SupplyType.INTRA,
            total_value_minor=11800,
            status=InvoiceStatus.CONFIRMED,
        )
        inv_probable = Invoice(
            gstin=gstin,
            fp=FP,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier,
            invoice_no=INV_PROBABLE,
            invoice_date=date(2026, 10, 2),
            place_of_supply="29",
            supply_type=SupplyType.INTRA,
            total_value_minor=20000,
            status=InvoiceStatus.CONFIRMED,
        )
        inv_unmatched = Invoice(
            gstin=gstin,
            fp=FP,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier,
            invoice_no=INV_UNMATCHED,
            invoice_date=date(2026, 10, 3),
            place_of_supply="29",
            supply_type=SupplyType.INTRA,
            total_value_minor=50000,
            status=InvoiceStatus.CONFIRMED,
        )
        inv_books_only = Invoice(
            gstin=gstin,
            fp=FP,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier,
            invoice_no=INV_BOOKS_ONLY,
            invoice_date=date(2026, 10, 4),
            place_of_supply="29",
            supply_type=SupplyType.INTRA,
            total_value_minor=15000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add_all([inv_matched, inv_probable, inv_unmatched, inv_books_only])
        await session.flush()

        # Books-side tax comes from the line rows (the same place the GSTR-3B
        # ITC table reads from).
        session.add_all(
            [
                InvoiceLine(
                    invoice_id=inv_matched.id,
                    line_no=1,
                    gst_rate=Decimal("18.00"),
                    taxable_value_minor=10000,
                    cgst_minor=900,
                    sgst_minor=900,
                    igst_minor=0,
                    cess_minor=0,
                ),
                InvoiceLine(
                    invoice_id=inv_probable.id,
                    line_no=1,
                    gst_rate=Decimal("18.00"),
                    taxable_value_minor=20000,
                    cgst_minor=1800,
                    sgst_minor=1800,
                    igst_minor=0,
                    cess_minor=0,
                ),
                InvoiceLine(
                    invoice_id=inv_unmatched.id,
                    line_no=1,
                    gst_rate=Decimal("18.00"),
                    taxable_value_minor=50000,
                    cgst_minor=4500,
                    sgst_minor=4500,
                    igst_minor=0,
                    cess_minor=0,
                ),
                InvoiceLine(
                    invoice_id=inv_books_only.id,
                    line_no=1,
                    gst_rate=Decimal("18.00"),
                    taxable_value_minor=15000,
                    cgst_minor=1350,
                    sgst_minor=1350,
                    igst_minor=0,
                    cess_minor=0,
                ),
            ]
        )
        await session.commit()

    # 2B: three of the four books invoices + one 2B-only row.
    payload = {
        "entries": [
            {
                "supplier_gstin": supplier,
                "invoice_no": INV_MATCHED,
                "invoice_date": "2026-10-01",
                "taxable_value_minor": 11800,
                "cgst_minor": 900,
                "sgst_minor": 900,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": INV_PROBABLE_2B,
                "invoice_date": "2026-10-02",
                "taxable_value_minor": 20000,
                "cgst_minor": 1800,
                "sgst_minor": 1800,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": INV_UNMATCHED,
                "invoice_date": "2026-10-03",
                "taxable_value_minor": 99999,
                "cgst_minor": 5000,
                "sgst_minor": 5000,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": INV_2B_ONLY,
                "invoice_date": "2026-10-05",
                "taxable_value_minor": 30000,
                "cgst_minor": 2700,
                "sgst_minor": 2700,
                "doc_type": "INV",
            },
        ]
    }
    imported = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/gstr2b/import",
        headers=headers,
        json={"payload": payload},
    )
    assert imported.status_code == 200, imported.text

    return gstin, headers


@pytest.mark.asyncio
async def test_itc_report_returns_five_statuses_with_both_sides(
    client: AsyncClient, api_sessionmaker
) -> None:
    gstin, headers = await _seed_period_with_books(client, api_sessionmaker)

    reconcile = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/reconcile", headers=headers
    )
    assert reconcile.status_code == 200, reconcile.text

    res = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/report", headers=headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    statuses = {row["match_status"] for row in data["rows"]}
    assert statuses == {
        "MATCHED",
        "PROBABLE",
        "UNMATCHED",
        "MISSING_IN_2B",
        "MISSING_IN_BOOKS",
    }

    # Counts cover every status (used to label the filter chips).
    counts = data["summary"]["counts"]
    assert counts["total"] == len(data["rows"]) == 5
    for key in statuses:
        assert counts[key] == 1

    # The MATCHED row carries both sides' paise figures — books side from the
    # invoice row, 2B side from the statement entry.
    matched = next(r for r in data["rows"] if r["match_status"] == "MATCHED")
    assert matched["books"]["invoice_no"] == INV_MATCHED
    assert matched["gstr2b"]["invoice_no"] == INV_MATCHED
    assert matched["books"]["total_value_paise"] == 11800
    assert matched["gstr2b"]["taxable_value_paise"] == 11800
    assert matched["gstr2b"]["total_paise"] == 900 + 900

    # MISSING_IN_2B has no 2B side; MISSING_IN_BOOKS has no books side.
    missing_2b = next(r for r in data["rows"] if r["match_status"] == "MISSING_IN_2B")
    assert missing_2b["gstr2b"] is None
    assert missing_2b["books"]["invoice_no"] == INV_BOOKS_ONLY

    missing_books = next(
        r for r in data["rows"] if r["match_status"] == "MISSING_IN_BOOKS"
    )
    assert missing_books["books"] is None
    assert missing_books["gstr2b"]["invoice_no"] == INV_2B_ONLY

    # 2B import status block.
    assert data["statement"] is not None
    assert data["statement"]["source"] == "PORTAL_UPLOAD"
    assert data["statement"]["entry_count"] == 4

    # ITC prefill totals are integer paise on both sides, and the delta is the
    # books total minus the 2B total for the same key (no float anywhere).
    books_itc = data["summary"]["books_itc_paise"]
    gstr2b_itc = data["summary"]["gstr2b_itc_paise"]
    for key in ("cgst_paise", "sgst_paise", "igst_paise", "cess_paise", "total_paise"):
        assert isinstance(books_itc[key], int)
        assert isinstance(gstr2b_itc[key], int)
        assert data["summary"]["delta_itc_paise"][key] == books_itc[key] - gstr2b_itc[key]
    # Hand-check on the fixture: 2B has 900+1800+5000+2700 = 10400 CGST paise
    # across its 4 eligible entries.
    assert gstr2b_itc["cgst_paise"] == 10400
    assert gstr2b_itc["total_paise"] == 10400 + 10400


@pytest.mark.asyncio
async def test_itc_report_status_filter(client: AsyncClient, api_sessionmaker) -> None:
    gstin, headers = await _seed_period_with_books(client, api_sessionmaker)
    await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/reconcile", headers=headers
    )

    res = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/report?status=MISSING_IN_2B",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert [r["match_status"] for r in data["rows"]] == ["MISSING_IN_2B"]
    # The filter narrows `rows` only; counts keep every status.
    assert data["summary"]["counts"]["total"] == 5

    bad = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/report?status=NOPE",
        headers=headers,
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_itc_report_empty_without_statement(
    client: AsyncClient, api_sessionmaker
) -> None:
    """No 2B import yet: an empty report, not an error (dashboard empty state)."""
    mobile = make_mobile()
    auth_data = await register_and_login(client, mobile)
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()
    await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={"gstin": gstin, "legal_name": "No 2B Co"},
    )

    res = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/itc/report", headers=headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["rows"] == []
    assert data["statement"] is None
    assert data["summary"]["counts"]["total"] == 0
    assert data["summary"]["books_itc_paise"]["total_paise"] == 0
    assert data["summary"]["gstr2b_itc_paise"]["total_paise"] == 0
