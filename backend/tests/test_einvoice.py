import uuid
from datetime import date

import pytest
from app.db.models.gst import Invoice, InvoiceDirection, InvoiceStatus, InvType, SupplyType
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker, make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin


@pytest.mark.asyncio
async def test_generate_and_cancel_irn(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    # 1. Setup
    auth_data = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()

    # Create GST Account
    await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={"gstin": gstin, "legal_name": "Test Company"},
    )
    await client.patch(
        f"/api/v1/gst-accounts/{gstin}",
        headers=headers,
        json={"aato_minor": 6000000000},
    )

    # Manually insert an Invoice
    inv_id = uuid.uuid4()
    async with api_sessionmaker() as session:
        invoice = Invoice(
            id=inv_id,
            gstin=gstin,
            fp="042026",
            direction=InvoiceDirection.SALES,
            invoice_no="INV-001",
            invoice_date=date(2026, 4, 1),
            place_of_supply="07",
            supply_type=SupplyType.INTER,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
            inv_typ=InvType.R,
        )
        session.add(invoice)
        await session.commit()

    # 2. Generate IRN
    irn_resp = await client.post(f"/api/v1/invoices/{inv_id}/irn", headers=headers)
    assert irn_resp.status_code == 200
    data = irn_resp.json()["data"]
    assert "irn" in data

    # 3. Idempotency
    irn_resp2 = await client.post(f"/api/v1/invoices/{inv_id}/irn", headers=headers)
    assert irn_resp2.status_code == 200
    assert irn_resp2.json()["data"]["irn"] == data["irn"]

    # 4. Cancel IRN
    cancel_resp = await client.post(f"/api/v1/einvoices/{inv_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert "cancelled_at" in cancel_resp.json()["data"]

@pytest.mark.asyncio
async def test_irn_applicable_gate(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    auth_data = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()

    # Create GST Account with irn_applicable = False
    await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={"gstin": gstin, "legal_name": "Test Company"},
    )
    await client.patch(
        f"/api/v1/gst-accounts/{gstin}",
        headers=headers,
        json={"aato_minor": 1000000000},
    )

    # Manually insert an Invoice
    inv_id = uuid.uuid4()
    async with api_sessionmaker() as session:
        invoice = Invoice(
            id=inv_id,
            gstin=gstin,
            fp="042026",
            direction=InvoiceDirection.SALES,
            invoice_no="INV-002",
            invoice_date=date(2026, 4, 1),
            place_of_supply="07",
            supply_type=SupplyType.INTER,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
            inv_typ=InvType.R,
        )
        session.add(invoice)
        await session.commit()

    # Generate IRN - Should fail
    irn_resp = await client.post(f"/api/v1/invoices/{inv_id}/irn", headers=headers)
    assert irn_resp.status_code == 400
