import pytest
from httpx import AsyncClient
from tests.auth_helpers import register_and_login, make_mobile
from tests.gstin_fixtures import make_gstin

import pytest
from httpx import AsyncClient
from tests.auth_helpers import register_and_login, make_mobile
from tests.gstin_fixtures import make_gstin
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.models.gst import Invoice, InvoiceDirection, SupplyType, InvoiceStatus
from datetime import date

@pytest.mark.asyncio
async def test_gstr2b_import_and_reconcile(client: AsyncClient, api_sessionmaker) -> None:
    # 1. Login and create GSTIN
    mobile = make_mobile()
    auth_data = await register_and_login(client, mobile)
    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    gstin = make_gstin()
    
    await client.post("/api/v1/gst-accounts", headers=headers, json={"gstin": gstin, "legal_name": "Test"})
    
    fp = "102026"
    
    # Seed local purchase invoices to test all 5 reconciliation statuses:
    # 1. MATCHED: Exact match in 2B and books
    # 2. PROBABLE: Fuzzy match (amount mismatch or typo in invoice no)
    # 3. UNMATCHED: Same invoice no, but completely different value
    # 4. MISSING_IN_2B: Present in books, missing in 2B
    # 5. MISSING_IN_BOOKS: Present in 2B, missing in books
    
    async with api_sessionmaker() as session:
        inv_matched = Invoice(
            gstin=gstin, fp=fp, direction=InvoiceDirection.PURCHASE,
            supplier_gstin="29AAAAA0000A1Z5", invoice_no="INV-MATCHED",
            invoice_date=date(2026, 10, 1), place_of_supply="29",
            supply_type=SupplyType.INTRA, total_value_minor=11800,
            status=InvoiceStatus.CONFIRMED
        )
        inv_probable = Invoice(
            gstin=gstin, fp=fp, direction=InvoiceDirection.PURCHASE,
            supplier_gstin="29AAAAA0000A1Z5", invoice_no="INV-PROBABL", # typo
            invoice_date=date(2026, 10, 2), place_of_supply="29",
            supply_type=SupplyType.INTRA, total_value_minor=20000,
            status=InvoiceStatus.CONFIRMED
        )
        inv_unmatched = Invoice(
            gstin=gstin, fp=fp, direction=InvoiceDirection.PURCHASE,
            supplier_gstin="29AAAAA0000A1Z5", invoice_no="INV-UNMATCHED",
            invoice_date=date(2026, 10, 3), place_of_supply="29",
            supply_type=SupplyType.INTRA, total_value_minor=50000,
            status=InvoiceStatus.CONFIRMED
        )
        inv_missing_in_2b = Invoice(
            gstin=gstin, fp=fp, direction=InvoiceDirection.PURCHASE,
            supplier_gstin="29AAAAA0000A1Z5", invoice_no="INV-ONLY-BOOKS",
            invoice_date=date(2026, 10, 4), place_of_supply="29",
            supply_type=SupplyType.INTRA, total_value_minor=15000,
            status=InvoiceStatus.CONFIRMED
        )
        session.add_all([inv_matched, inv_probable, inv_unmatched, inv_missing_in_2b])
        await session.commit()

    # 2. Import 2B JSON containing:
    # - INV-MATCHED (Exact)
    # - INV-PROBABLE (Fuzzy invoice no match)
    # - INV-UNMATCHED (Same invoice no, different amount)
    # - INV-ONLY-2B (Missing in books)
    payload = {
        "entries": [
            {
                "supplier_gstin": "29AAAAA0000A1Z5",
                "invoice_no": "INV-MATCHED",
                "invoice_date": "2026-10-01",
                "taxable_value_minor": 11800,
                "cgst_minor": 900,
                "sgst_minor": 900,
                "doc_type": "INV"
            },
            {
                "supplier_gstin": "29AAAAA0000A1Z5",
                "invoice_no": "INV-PROBABLE",
                "invoice_date": "2026-10-02",
                "taxable_value_minor": 20000,
                "cgst_minor": 1800,
                "sgst_minor": 1800,
                "doc_type": "INV"
            },
            {
                "supplier_gstin": "29AAAAA0000A1Z5",
                "invoice_no": "INV-UNMATCHED",
                "invoice_date": "2026-10-03",
                "taxable_value_minor": 99999, # different
                "cgst_minor": 5000,
                "sgst_minor": 5000,
                "doc_type": "INV"
            },
            {
                "supplier_gstin": "29AAAAA0000A1Z5",
                "invoice_no": "INV-ONLY-2B",
                "invoice_date": "2026-10-05",
                "taxable_value_minor": 30000,
                "cgst_minor": 2700,
                "sgst_minor": 2700,
                "doc_type": "INV"
            }
        ]
    }
    response = await client.post(f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr2b/import", headers=headers, json={"payload": payload})
    assert response.status_code == 200
    
    # 3. Reconcile
    response = await client.post(f"/api/v1/gst-accounts/{gstin}/months/{fp}/itc/reconcile", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    
    # Verify all 5 statuses are present
    statuses = [item["match_status"] for item in data]
    assert "MATCHED" in statuses
    assert "PROBABLE" in statuses
    assert "UNMATCHED" in statuses
    assert "MISSING_IN_2B" in statuses
    assert "MISSING_IN_BOOKS" in statuses
