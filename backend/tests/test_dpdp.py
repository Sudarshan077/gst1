"""DPDP compliance tests: export, erasure SLA, 8-FY retention carve-out, audit.

Covers SECURITY_AND_ACCESS.md §4:
  - Self-service export returns JSON + CSV + documents manifest.
  - Erasure request enters SLA_QUEUED with 30-day SLA and carve-out flag.
  - Retention job closes SLA-expired requests and applies the 8-FY carve-out.
  - Audit rows are written for export/erasure/retention-completion.
  - Routes are step-up and access-guard protected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core.auth.tokens import create_stepup_token, verify_access_token
from app.db.models.core import AuditLog
from app.db.models.dpdp import DPDPRequest, DPDPRequestStatus, DPDPRequestType
from app.db.models.extraction import Document
from app.db.models.gst import Invoice, InvoiceStatus
from app.services.dpdp import request_erasure
from app.services.retention import run_retention_job
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_email, register_and_login
from tests.gstin_fixtures import gstin_checksum_valid
from tests.v4_helpers import seed_account

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


async def test_dpdp_export_returns_json_csv_and_manifest(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, legal_name="Export Test Co"
    )
    user_id = verify_access_token(tokens["access_token"])
    gstin = account.gstin
    assert gstin_checksum_valid(gstin)

    # Seed one invoice and one document so the export has real rows.
    async with api_sessionmaker() as session:
        session.add(
            Invoice(
                gstin=gstin,
                fp="072025",
                direction="SALES",
                invoice_no="EXP-001",
                invoice_date=datetime(2025, 7, 15, tzinfo=UTC).date(),
                place_of_supply=gstin[:2],
                supply_type="INTRA",
                rchrg=False,
                inv_typ="R",
                total_value_minor=125_00,
                status=InvoiceStatus.CONFIRMED,
                confirmed_by=user_id,
                confirmed_at=datetime.now(UTC),
            )
        )
        session.add(
            Document(
                gstin=gstin,
                fp="072025",
                capture_source="DIGITAL",
                doc_type="INV",
                minio_key=f"{gstin}/072025/doc-1.pdf",
                sha256="a" * 64,
                bytes=1024,
                uploaded_by=user_id,
            )
        )
        await session.commit()

    stepup = create_stepup_token(user_id)
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/dpdp/export",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Stepup-Token": stepup,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "COMPLETED"
    export = data["export"]
    assert export["gstin"] == gstin
    assert export["account"]["legal_name"] == "Export Test Co"
    assert len(export["invoices"]) == 1
    assert export["invoices"][0]["total_value_paise"] == 125_00
    assert len(export["documents_manifest"]) == 1
    assert export["documents_manifest"][0]["sha256"] == "a" * 64
    assert "csv_manifest" in export
    assert "minio_key,sha256" in export["csv_manifest"]

    # Audit row recorded.
    async with api_sessionmaker() as session:
        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.gstin == gstin, AuditLog.action == "DPDP_EXPORT"
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert str(audit.actor_user_id) == str(user_id)


async def test_dpdp_erasure_request_sla_and_carve_out(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, legal_name="Erasure Test Co"
    )
    user_id = verify_access_token(tokens["access_token"])
    gstin = account.gstin

    stepup = create_stepup_token(user_id)
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/dpdp/erasure",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Stepup-Token": stepup,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "SLA_QUEUED"
    assert data["retention_carve_out_applied"] is True
    assert data["sla_days"] == 30
    assert "sla_due_date" in data

    async with api_sessionmaker() as session:
        req = await session.get(DPDPRequest, data["request_id"])
        assert req is not None
        assert req.request_type == DPDPRequestType.ERASURE
        assert req.status == DPDPRequestStatus.SLA_QUEUED
        assert req.retention_carve_out_applied is True
        assert req.sla_due_date is not None

        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.gstin == gstin, AuditLog.action == "DPDP_ERASURE_REQUEST"
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.payload_diff is not None
        assert audit.payload_diff.get("sla_days") == 30


async def test_retention_job_closes_sla_expired_erasure_and_carves_out(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, legal_name="Retention Test Co"
    )
    user_id = verify_access_token(tokens["access_token"])
    gstin = account.gstin

    async with api_sessionmaker() as session:
        await request_erasure(session, user_id, gstin)
        # Backdate the request so its SLA is already expired.
        req = (
            await session.execute(
                select(DPDPRequest).where(
                    DPDPRequest.gstin == gstin,
                    DPDPRequest.request_type == DPDPRequestType.ERASURE,
                )
            )
        ).scalar_one()
        req.sla_due_date = datetime.now(UTC) - timedelta(days=1)
        req.created_at = datetime.now(UTC) - timedelta(days=365 * 9)
        await session.commit()

    async with api_sessionmaker() as session:
        summary = await run_retention_job(session)
        assert summary["completed"] == 1

    async with api_sessionmaker() as session:
        req = await session.get(DPDPRequest, req.id)
        assert req.status == DPDPRequestStatus.COMPLETED
        # Older than 8 FYs -> carve-out no longer applies.
        assert req.retention_carve_out_applied is False
        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.gstin == gstin,
                    AuditLog.action == "DPDP_ERASURE_COMPLETED",
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.payload_diff is not None
        assert audit.payload_diff.get("retention_carve_out") is False
        assert audit.payload_diff.get("sla_met") is True


async def test_dpdp_export_status_route(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, _account = await seed_account(
        client, api_sessionmaker, legal_name="Export Status Co"
    )
    user_id = verify_access_token(tokens["access_token"])

    stepup = create_stepup_token(user_id)
    resp = await client.post(
        "/api/v1/me/data/export",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Stepup-Token": stepup,
        },
    )
    assert resp.status_code == 200, resp.text
    request_id = resp.json()["data"]["request_id"]

    status_resp = await client.get(
        f"/api/v1/me/data/export/{request_id}",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["status"] == "COMPLETED"


async def test_dpdp_export_requires_stepup_and_guard(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(
        client, api_sessionmaker, legal_name="Guarded Co"
    )
    gstin = account.gstin

    # No step-up token -> 401/403 step-up required.
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/dpdp/export",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 401 or resp.status_code == 403


async def test_dpdp_me_routes_fail_without_gstin(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """A user with no GSTIN cannot hit /me/data endpoints with a fabricated default."""
    tokens = await register_and_login(client, make_email())
    user_id = verify_access_token(tokens["access_token"])
    stepup = create_stepup_token(user_id)
    resp = await client.post(
        "/api/v1/me/data/export",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Stepup-Token": stepup,
        },
    )
    assert resp.status_code == 404, resp.text
