"""Unit + light integration tests for app/services/returns/*.

Pushes coverage on the returns service modules toward the 80% floor.
All GSTINs are synthetic fixtures; money is integer paise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.errors import ServiceError
from app.core.auth.tokens import verify_access_token
from app.db.models.gst import (
    EInvoice,
    ExportType,
    FilingPeriod,
    FilingStatus,
    Gstr1Export,
    Invoice,
    InvoiceDirection,
    InvoiceStatus,
    SupplyType,
)
from app.services.returns import gsp_adapter, gstr1a, gstr2b, irp_live_adapter
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account, seed_open_period

pytestmark = pytest.mark.asyncio


async def _seed_filed_period_and_export(
    sessionmaker: async_sessionmaker, gstin: str, fp: str, user_id: uuid.UUID
) -> Gstr1Export:
    async with sessionmaker() as session:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="REGULAR_MONTHLY",
            status=FilingStatus.FILED,
            filed_at=datetime.now(UTC),
            filed_by=user_id,
        )
        export = Gstr1Export(
            gstin=gstin,
            fp=fp,
            generated_by=user_id,
            json_minio_key=f"gstr1/{gstin}/{fp}/export.json",
            invoice_count=1,
            totals={"taxable_value_minor": 100000},
            schema_version="1.0",
            export_type=ExportType.ORIGINAL,
        )
        session.add(period)
        session.add(export)
        await session.commit()
        await session.refresh(export)
        return export


async def _seed_open_period_with_invoice(
    sessionmaker: async_sessionmaker,
    gstin: str,
    fp: str,
    supplier_gstin: str,
    invoice_no: str,
    total_value_minor: int,
    seed_period: bool = True,
) -> uuid.UUID:
    if seed_period:
        await seed_open_period(sessionmaker, gstin, fp)
    async with sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier_gstin,
            invoice_no=invoice_no,
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=total_value_minor,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)
        return invoice.id


async def test_gstr1a_requires_filed_period(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc_info:
            await gstr1a.create_gstr1a_amendments(
                session, gstin, fp, {"amendments": []}
            )
        assert exc_info.value.code == "PERIOD_NOT_FILED"


async def test_gstr1a_requires_export(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="REGULAR_MONTHLY",
            status=FilingStatus.FILED,
            filed_at=datetime.now(UTC),
            filed_by=user_id,
        )
        session.add(period)
        await session.commit()

        with pytest.raises(ServiceError) as exc_info:
            await gstr1a.create_gstr1a_amendments(
                session, gstin, fp, {"amendments": []}
            )
        assert exc_info.value.code == "EXPORT_NOT_FOUND"


async def test_gstr1a_creates_amendments(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = verify_access_token(tokens["access_token"])
    export = await _seed_filed_period_and_export(
        api_sessionmaker, gstin, fp, user_id
    )
    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            invoice_no="GSTR1A-INV-001",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=100000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)
        inv_id = invoice.id

    async with api_sessionmaker() as session:
        created = await gstr1a.create_gstr1a_amendments(
            session,
            gstin,
            fp,
            {
                "amendments": [
                    {
                        "invoice_id": str(inv_id),
                        "field_deltas": {"total_value_minor": 120000},
                        "reason": "Price correction",
                    }
                ]
            },
        )

    assert len(created) == 1
    assert created[0]["target_export_id"] == str(export.id)
    assert created[0]["reason"] == "Price correction"


async def test_gstr2b_import_and_reconcile_all_statuses(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    supplier = make_gstin(state_code="29")
    user_id = verify_access_token(tokens["access_token"])

    await seed_open_period(api_sessionmaker, gstin, fp)
    await _seed_open_period_with_invoice(
        api_sessionmaker, gstin, fp, supplier, "INV-MATCHED", 11800, seed_period=False
    )
    await _seed_open_period_with_invoice(
        api_sessionmaker, gstin, fp, supplier, "INV-PROBABL", 20000, seed_period=False
    )
    await _seed_open_period_with_invoice(
        api_sessionmaker, gstin, fp, supplier, "INV-UNMATCHED", 50000, seed_period=False
    )
    await _seed_open_period_with_invoice(
        api_sessionmaker, gstin, fp, supplier, "INV-ONLY-BOOKS", 15000, seed_period=False
    )

    payload = {
        "entries": [
            {
                "supplier_gstin": supplier,
                "invoice_no": "INV-MATCHED",
                "invoice_date": "2026-10-01",
                "taxable_value_minor": 11800,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": "INV-PROBABLE",
                "invoice_date": "2026-10-02",
                "taxable_value_minor": 20000,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": "INV-UNMATCHED",
                "invoice_date": "2026-10-03",
                "taxable_value_minor": 99999,
                "doc_type": "INV",
            },
            {
                "supplier_gstin": supplier,
                "invoice_no": "INV-ONLY-2B",
                "invoice_date": "2026-10-05",
                "taxable_value_minor": 30000,
                "doc_type": "INV",
            },
        ]
    }

    async with api_sessionmaker() as session:
        statement = await gstr2b.import_gstr2b(session, gstin, fp, payload, user_id)
        assert statement.gstin == gstin
        assert statement.fp == fp

        recons = await gstr2b.reconcile_itc(session, gstin, fp)

    statuses = {r.match_status.value for r in recons}
    assert "MATCHED" in statuses
    assert "PROBABLE" in statuses
    assert "UNMATCHED" in statuses
    assert "MISSING_IN_2B" in statuses
    assert "MISSING_IN_BOOKS" in statuses


async def test_gstr2b_reconcile_no_statement(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"

    async with api_sessionmaker() as session:
        recons = await gstr2b.reconcile_itc(session, gstin, fp)
    assert recons == []


async def test_gsp_file_gstr1_creates_period(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        result = await gsp_adapter.file_gstr1_gsp(session, gstin, fp, user_id)
        assert result["success"] is True
        assert result["status"] == "FILED"

        period = await session.get(FilingPeriod, (gstin, fp))
        assert period is not None
        assert period.status.value == "FILED"


async def test_gsp_file_gstr3b_updates_period(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = verify_access_token(tokens["access_token"])
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        result = await gsp_adapter.file_gstr3b_gsp(session, gstin, fp, user_id)
        assert result["success"] is True
        assert result["status"] == "FILED"

        period = await session.get(FilingPeriod, (gstin, fp))
        assert period.status.value == "FILED"


async def test_gsp_fetch_gstr2b_idempotent(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        first = await gsp_adapter.fetch_gstr2b_gsp(session, gstin, fp, user_id)
        second = await gsp_adapter.fetch_gstr2b_gsp(session, gstin, fp, user_id)
        assert first.id == second.id
        assert first.source.value == "GSP_API"


async def test_irp_live_adapter_sandbox_mode_blocks(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc_info:
            await irp_live_adapter.generate_live_irn(
                session, uuid.uuid4(), uuid.uuid4()
            )
        assert exc_info.value.code == "INVALID_OPERATION"


async def test_irp_live_adapter_missing_credentials(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "dev-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ):
        async with api_sessionmaker() as session:
            with pytest.raises(ServiceError) as exc_info:
                await irp_live_adapter.generate_live_irn(
                    session, uuid.uuid4(), uuid.uuid4()
                )
            assert exc_info.value.code == "UNAUTHORIZED"


async def test_irp_live_adapter_invoice_not_found(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ):
        async with api_sessionmaker() as session:
            with pytest.raises(ServiceError) as exc_info:
                await irp_live_adapter.generate_live_irn(
                    session, uuid.uuid4(), uuid.uuid4()
                )
            assert exc_info.value.code == "NOT_FOUND"


async def test_irp_live_adapter_irn_not_applicable(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-001",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)

    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ):
        async with api_sessionmaker() as session:
            with pytest.raises(ServiceError) as exc_info:
                await irp_live_adapter.generate_live_irn(
                    session, invoice.id, uuid.uuid4()
                )
            assert exc_info.value.code == "INVALID_OPERATION"


async def test_irp_live_adapter_existing_einvoice_returns(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-002",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.flush()
        existing = EInvoice(
            invoice_id=invoice.id,
            irn=f"MOCK-IRN-{uuid.uuid4().hex[:12].upper()}",
            ack_no="ACK-1",
            ack_date=datetime.now(UTC),
            signed_qr_base64="qr",
            cancel_window_until=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(existing)
        await session.commit()
        inv_id = invoice.id

    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ):
        async with api_sessionmaker() as session:
            result = await irp_live_adapter.generate_live_irn(
                session, inv_id, uuid.uuid4()
            )
            assert result.irn == existing.irn


async def test_irp_live_adapter_generate_and_cancel_success(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-003",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)
        inv_id = invoice.id

    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    async def fake_post(url, **kwargs):
        class Resp:
            status_code = 200
            text = "OK"
        if "authenticate" in str(url):
            resp = Resp()
            resp.json = lambda: {"Data": {"AuthToken": "live-token-123"}}
            return resp
        if "cancel" in str(url):
            resp = Resp()
            resp.json = lambda: {"Status": "1", "Desc": "IRN cancelled successfully"}
            return resp
        resp = Resp()
        resp.json = lambda: {
            "Irn": f"NIC-IRN-{uuid.uuid4().hex[:12].upper()}",
            "AckNo": "123456789",
            "AckDt": "01/10/2026 12:34:56",
            "SignedQRCode": "base64-qr",
        }
        return resp

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ), patch("httpx.AsyncClient", return_value=fake_client):
        async with api_sessionmaker() as session:
            einv = await irp_live_adapter.generate_live_irn(session, inv_id, uuid.uuid4())
            assert einv.irn.startswith("NIC-IRN-")
            assert einv.ack_no == "123456789"
            assert einv.cancel_window_until is not None

            cancelled = await irp_live_adapter.cancel_live_irn(
                session, inv_id, uuid.uuid4()
            )
            assert cancelled.cancelled_at is not None


async def test_irp_live_adapter_cancel_already_cancelled(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-004",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.flush()
        einv = EInvoice(
            invoice_id=invoice.id,
            irn=f"MOCK-IRN-{uuid.uuid4().hex[:12].upper()}",
            ack_no="ACK-4",
            ack_date=datetime.now(UTC),
            signed_qr_base64="qr",
            cancel_window_until=datetime.now(UTC) + timedelta(hours=24),
            cancelled_at=datetime.now(UTC),
        )
        session.add(einv)
        await session.commit()
        inv_id = invoice.id

    with pytest.raises(ServiceError) as exc_info:
        async with api_sessionmaker() as session:
            await irp_live_adapter.cancel_live_irn(session, inv_id, uuid.uuid4())
    assert exc_info.value.code == "INVALID_OPERATION"


async def test_irp_live_adapter_cancel_window_expired(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-005",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.flush()
        einv = EInvoice(
            invoice_id=invoice.id,
            irn=f"MOCK-IRN-{uuid.uuid4().hex[:12].upper()}",
            ack_no="ACK-5",
            ack_date=datetime.now(UTC) - timedelta(hours=48),
            signed_qr_base64="qr",
            cancel_window_until=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(einv)
        await session.commit()
        inv_id = invoice.id

    with pytest.raises(ServiceError) as exc_info:
        async with api_sessionmaker() as session:
            await irp_live_adapter.cancel_live_irn(session, inv_id, uuid.uuid4())
    assert exc_info.value.code == "INVALID_OPERATION"

async def test_gsp_file_gstr1_creates_period_when_none(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    """GSP GSTR-1 filing creates a new FilingPeriod when none exists."""
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "112026"
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        result = await gsp_adapter.file_gstr1_gsp(session, gstin, fp, user_id)
        assert result["success"] is True
        period = await session.get(FilingPeriod, (gstin, fp))
        assert period is not None
        assert period.status.value == "FILED"


async def test_gstr2b_reconcile_amount_mismatch_probable(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    """GSTR-2B reconcile marks an invoice with a small amount delta as PROBABLE."""
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    supplier = make_gstin(state_code="29")
    user_id = verify_access_token(tokens["access_token"])

    await seed_open_period(api_sessionmaker, gstin, fp)
    await _seed_open_period_with_invoice(
        api_sessionmaker, gstin, fp, supplier, "INV-DELTA", 11800, seed_period=False
    )

    payload = {
        "entries": [
            {
                "supplier_gstin": supplier,
                "invoice_no": "INV-DELTA",
                "invoice_date": "2026-10-01",
                "taxable_value_minor": 11850,
                "doc_type": "INV",
            }
        ]
    }

    async with api_sessionmaker() as session:
        await gstr2b.import_gstr2b(session, gstin, fp, payload, user_id)
        recons = await gstr2b.reconcile_itc(session, gstin, fp)

    assert len(recons) == 1
    assert recons[0].match_status.value == "PROBABLE"
    assert recons[0].confidence == 0.8

async def test_irp_live_adapter_generate_http_error(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    """Live IRP generate surfaces a 502 BAD_GATEWAY when NIC returns non-200."""
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-HTTP-ERR",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)
        inv_id = invoice.id

    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    err_response = type("Resp", (), {"status_code": 500, "text": "NIC error"})()

    async def fake_post(url, **kwargs):
        if "authenticate" in str(url):
            auth = type("Resp", (), {"status_code": 200})()
            auth.json = lambda: {"Data": {"AuthToken": "live-token-123"}}
            return auth
        return err_response

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ), patch("httpx.AsyncClient", return_value=fake_client):
        async with api_sessionmaker() as session:
            with pytest.raises(ServiceError) as exc_info:
                await irp_live_adapter.generate_live_irn(session, inv_id, uuid.uuid4())
            assert exc_info.value.code == "BAD_GATEWAY"


async def test_irp_live_adapter_cancel_http_error(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    """Live IRP cancel surfaces a 502 BAD_GATEWAY when NIC returns non-200."""
    tokens, account = await seed_account(
        client, api_sessionmaker, state_code="27", aato_minor=7_000_000_000
    )
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    async with api_sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=make_gstin(state_code="29"),
            invoice_no="IRN-CANCEL-ERR",
            invoice_date=date(2026, 10, 1),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            total_value_minor=118000,
            status=InvoiceStatus.CONFIRMED,
        )
        session.add(invoice)
        await session.flush()
        einv = EInvoice(
            invoice_id=invoice.id,
            irn=f"MOCK-IRN-{uuid.uuid4().hex[:12].upper()}",
            ack_no="ACK-CANCEL",
            ack_date=datetime.now(UTC),
            signed_qr_base64="qr",
            cancel_window_until=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(einv)
        await session.commit()
        inv_id = invoice.id

    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    err_response = type("Resp", (), {"status_code": 500, "text": "NIC error"})()

    async def fake_post(url, **kwargs):
        if "authenticate" in str(url):
            auth = type("Resp", (), {"status_code": 200})()
            auth.json = lambda: {"Data": {"AuthToken": "live-token-123"}}
            return auth
        return err_response

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ), patch("httpx.AsyncClient", return_value=fake_client):
        async with api_sessionmaker() as session:
            with pytest.raises(ServiceError) as exc_info:
                await irp_live_adapter.cancel_live_irn(session, inv_id, uuid.uuid4())
            assert exc_info.value.code == "BAD_GATEWAY"


async def test_irp_live_adapter_auth_failure(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    """Live IRP auth failure raises UNAUTHORIZED."""
    settings = MagicMock()
    settings.irp_sandbox_mode = False
    settings.irp_client_id = "real-client-id"
    settings.irp_username = "dev-username"
    settings.irp_password = "dev-password"
    settings.irp_client_secret = "dev-client-secret"
    settings.irp_api_base_url = "https://einvoice1-trial.nic.in"

    err_response = type("Resp", (), {"status_code": 401, "text": "bad creds"})()

    async def fake_post(*a, **kw):
        return err_response

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch(
        "app.services.returns.irp_live_adapter.get_settings", return_value=settings
    ), patch("httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(ServiceError) as exc_info:
            await irp_live_adapter._authenticate_live_irp(settings)
        assert exc_info.value.code == "UNAUTHORIZED"

