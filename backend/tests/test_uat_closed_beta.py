"""Task 5.5 — UAT closed beta simulation + critical-path regression.

One synthetic "sample user" walks the full platform surface:
  register → add GSTIN → upload document → review/confirm →
  GSTR-1 prepare/generate → mark filed → 2B import/reconcile →
  sandbox IRN → notifications.

All GSTINs/PANs are synthetic fixtures (AI_BUILD_PLAYBOOK hard rule #1).
Money is integer paise everywhere (hard rule #2). Locked period returns 423.
"""

from __future__ import annotations

import io
import random
import uuid

import pytest
from app.db.models.extraction import ExtractionJob, InvoiceDraft, JobStatus
from app.db.models.gst import Invoice, InvoiceStatus
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_open_period

pytestmark = pytest.mark.asyncio


def _minimal_png() -> bytes:
    # Vary pixel content so each upload has a unique sha256.
    # Not crypto — only image-content uniqueness is needed (S311 exempt).
    color = tuple(random.SystemRandom().randint(0, 255) for _ in range(3))
    img = Image.new("RGB", (10, 10), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _seed_sample_user(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> tuple[dict, dict, str, str, str]:
    mobile = make_mobile()
    auth = await register_and_login(client, mobile)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    supplier_gstin = make_gstin(state_code="27")
    reg_gstin = make_gstin(state_code="27")
    fp = "102026"

    r = await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={
            "gstin": reg_gstin,
            "legal_name": "Beta Sample Pvt Ltd",
            "trade_name": "Beta Sample",
            "aato_minor": 7_000_000_000,  # >5cr → IRN applicable
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["irn_applicable"] is True

    await seed_open_period(api_sessionmaker, reg_gstin, fp)
    return auth, headers, supplier_gstin, reg_gstin, fp


async def _upload_and_seed_draft(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker,
    headers: dict,
    supplier_gstin: str,
    reg_gstin: str,
    fp: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PHOTO"},
        files={"files": ("bill.png", io.BytesIO(_minimal_png()), "image/png")},
    )
    assert r.status_code == 200, r.text
    doc_id = uuid.UUID(r.json()["data"]["id"])

    async with api_sessionmaker() as session:
        job = (
            await session.execute(
                select(ExtractionJob).where(ExtractionJob.document_id == doc_id)
            )
        ).scalar_one()
        job.status = JobStatus.EXTRACTED

        draft = InvoiceDraft(
            extraction_job_id=job.id,
            gstin=reg_gstin,
            fp=fp,
            payload={
                "fields": {
                    "supplier_gstin": supplier_gstin,
                    "buyer_gstin": reg_gstin,
                    "invoice_no": "BETA-001",
                    "invoice_date": "2026-10-05",
                    "place_of_supply": "27",
                    "is_inter_state": False,
                    "rchrg": False,
                    "inv_typ": "R",
                    "taxable_value_paise": 100000,
                    "total_value_paise": 118000,
                    "cgst_paise": 9000,
                    "sgst_paise": 9000,
                    "igst_paise": 0,
                    "cess_paise": 0,
                },
                "lines": [
                    {
                        "desc": "Professional services",
                        "hsn_sac": "998314",
                        "uqc": "OTH",
                        "qty": 1,
                        "unit_price_paise": 100000,
                        "gst_rate": 18,
                        "taxable_value_paise": 100000,
                    }
                ],
            },
            field_confidence={
                k: 0.99
                for k in [
                    "supplier_gstin",
                    "buyer_gstin",
                    "invoice_no",
                    "invoice_date",
                    "place_of_supply",
                    "is_inter_state",
                    "rchrg",
                    "inv_typ",
                    "taxable_value_paise",
                    "total_value_paise",
                    "cgst_paise",
                    "sgst_paise",
                    "igst_paise",
                    "cess_paise",
                ]
            },
        )
        session.add(draft)
        await session.commit()

    return doc_id, job.id


async def test_uat_beta_full_journey(client: AsyncClient, api_sessionmaker):
    auth, headers, supplier_gstin, reg_gstin, fp = await _seed_sample_user(
        client, api_sessionmaker
    )

    # Upload + seed draft
    doc_id, _job_id = await _upload_and_seed_draft(
        client, api_sessionmaker, headers, supplier_gstin, reg_gstin, fp
    )

    # GET /documents/{doc_id}/draft
    r = await client.get(f"/api/v1/documents/{doc_id}/draft", headers=headers)
    assert r.status_code == 200, r.text
    draft_data = r.json()["data"]
    assert draft_data["fields"]["invoice_no"] == "BETA-001"

    # PUT /documents/{doc_id}/draft (human edits one field)
    r = await client.put(
        f"/api/v1/documents/{doc_id}/draft",
        headers=headers,
        json={"invoice_no": "BETA-001-EDITED"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["fields"]["invoice_no"] == "BETA-001-EDITED"

    # Confirm the invoice
    r = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    inv_id = uuid.UUID(r.json()["data"]["invoice_id"])

    # Duplicate confirm is idempotent-ish (409 already confirmed)
    r2 = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert r2.status_code == 409

    # Invoice row exists in DB
    async with api_sessionmaker() as session:
        invoice = await session.get(Invoice, inv_id)
        assert invoice is not None
        assert invoice.status == InvoiceStatus.CONFIRMED
        assert invoice.total_value_minor == 118000

    # GSTR-1 prepare / generate
    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/gstr1/prepare",
        headers=headers,
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/gstr1/generate",
        headers=headers,
    )
    assert r.status_code == 200
    export_id = r.json()["data"]["export_id"]
    assert uuid.UUID(export_id)

    # Seed a second document before filing; confirm after filing must be 423.
    doc2_id, _ = await _upload_and_seed_draft(
        client, api_sessionmaker, headers, supplier_gstin, reg_gstin, fp
    )

    # Mark filed → period locked
    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/filed",
        headers=headers,
    )
    assert r.status_code == 200

    r = await client.post(f"/api/v1/documents/{doc2_id}/confirm", headers=headers)
    assert r.status_code == 423

    # GSTR-1A allowed post-file
    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/gstr1a",
        headers=headers,
        json={
            "amendments": [
                {
                    "invoice_id": str(inv_id),
                    "field_deltas": {"total_value_minor": 120000},
                    "reason": "Price correction",
                }
            ]
        },
    )
    assert r.status_code == 200
    assert len(r.json()["data"]["amendments"]) == 1

    # 2B import + reconcile (payload wrapper required by schema)
    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/gstr2b/import",
        headers=headers,
        json={
            "payload": {
                "entries": [
                    {
                        "supplier_gstin": supplier_gstin,
                        "invoice_no": "BETA-001-EDITED",
                        "invoice_date": "2026-10-05",
                        "taxable_value_minor": 118000,
                        "cgst_minor": 9000,
                        "sgst_minor": 9000,
                        "igst_minor": 0,
                        "doc_type": "INV",
                    }
                ]
            }
        },
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/gst-accounts/{reg_gstin}/months/{fp}/itc/reconcile",
        headers=headers,
    )
    assert r.status_code == 200

    # Sandbox IRN (IRN applicable because AATO >5cr)
    r = await client.post(f"/api/v1/invoices/{inv_id}/irn", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["irn"].startswith("MOCK-IRN-")

    # IRN idempotent
    r = await client.post(f"/api/v1/invoices/{inv_id}/irn", headers=headers)
    assert r.status_code == 200

    # Notifications endpoints work
    r = await client.get("/api/v1/notifications", headers=headers)
    assert r.status_code == 200

    r = await client.get("/api/v1/me/notification-prefs", headers=headers)
    assert r.status_code == 200

    r = await client.patch(
        "/api/v1/me/notification-prefs",
        headers=headers,
        json={"email": True},
    )
    assert r.status_code == 200
    assert r.json()["prefs"]["email"] is True
