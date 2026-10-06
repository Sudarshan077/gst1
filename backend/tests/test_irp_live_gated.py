import uuid
from datetime import date

import pytest
from app.config import get_settings
from app.db.models.gst import Invoice, InvoiceDirection, InvoiceStatus, InvType, SupplyType
from app.services.returns import irp_live_adapter
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker, make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin


@pytest.mark.asyncio
async def test_live_irp_credential_gate(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    auth_data = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()

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

    inv_id = uuid.uuid4()
    async with api_sessionmaker() as session:
        invoice = Invoice(
            id=inv_id,
            gstin=gstin,
            fp="042026",
            direction=InvoiceDirection.SALES,
            invoice_no="INV-LIVE-01",
            invoice_date=date(2026, 4, 1),
            place_of_supply="07",
            supply_type=SupplyType.INTER,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
            inv_typ=InvType.R,
        )
        session.add(invoice)
        await session.commit()

    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = uuid.UUID(me.json()["data"]["user"]["id"])
    settings = get_settings()
    settings.irp_sandbox_mode = True

    async with api_sessionmaker() as session:
        with pytest.raises(Exception) as exc_info:
            await irp_live_adapter.generate_live_irn(session, inv_id, user_id)
        assert (
            "irp_sandbox_mode is True" in str(exc_info.value)
            or "ServiceError" in type(exc_info.value).__name__
        )

    # Test that when sandbox_mode=False but credentials are default/missing, it raises UNAUTHORIZED
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "dev-client-id"

    async with api_sessionmaker() as session:
        with pytest.raises(Exception) as exc_info:
            await irp_live_adapter.generate_live_irn(session, inv_id, user_id)
        # Should raise due to missing/default credentials
        assert (
            "credentials missing" in str(exc_info.value).lower()
            or "UNAUTHORIZED" in str(exc_info.value)
            or "ServiceError" in type(exc_info.value).__name__
        )

    # Reset settings back to default sandbox
    settings.irp_sandbox_mode = True
    settings.irp_client_id = "dev-client-id"
