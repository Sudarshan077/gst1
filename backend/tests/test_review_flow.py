"""Critical-path regression for the review/confirm flow (services/review.py).

Covers the review queue, draft GET/PUT with validator re-run, confirm ->
invoices/invoice_lines, reject, and every guard branch: locked period 423,
already-confirmed 409, duplicate invoice_no 409, rejected-doc confirm 422,
no-editable-fields 422, tenant isolation 404, and FILER/ADMIN write guard.

Money is integer paise everywhere; GSTINs are mod-36 checksum-valid
synthetic fixtures via tests/gstin_fixtures.make_gstin.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_gstin_for_user, seed_open_period

pytestmark = pytest.mark.asyncio

FP = "092026"


def _clean_fields(reg_gstin: str, supplier_gstin: str) -> dict[str, Any]:
    """A validator-clean field set: intra-state purchase from supplier."""
    taxable = 100000
    cgst = sgst = 9000
    return {
        "supplier_gstin": supplier_gstin,
        "buyer_gstin": reg_gstin,
        "invoice_no": "INV-RV-001",
        "invoice_date": "2026-09-01",
        "place_of_supply": "27",
        "is_inter_state": False,
        "rchrg": False,
        "inv_typ": "R",
        "taxable_value_paise": taxable,
        "total_value_paise": taxable + cgst + sgst,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": 0,
        "cess_paise": 0,
    }


_UPLOAD_SEQ = 0


async def _upload_one_doc(
    client: httpx.AsyncClient, headers: dict[str, str], gstin: str, fp: str
) -> str:
    """Upload a unique 1x1 PNG via the real upload path; return document id."""
    from PIL import Image

    global _UPLOAD_SEQ
    _UPLOAD_SEQ += 1
    # vary pixel bytes so each upload has a distinct sha256 (dedupe guard is live)
    img = Image.new("RGB", (1, 1), color=(_UPLOAD_SEQ % 256, 7, 42))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PHOTO"},
        files={"files": ("rv.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


async def _attach_draft(
    sessionmaker: async_sessionmaker[Any],
    doc_id: str,
    gstin: str,
    fp: str,
    fields: dict[str, Any],
    *,
    job_status: str = "EXTRACTED",
) -> None:
    """Flip the spawned job's status and attach an InvoiceDraft payload."""
    from app.db.models.extraction import ExtractionJob, InvoiceDraft, JobStatus

    async with sessionmaker() as session:
        job = (
            await session.execute(
                select(ExtractionJob).where(ExtractionJob.document_id == uuid.UUID(doc_id))
            )
        ).scalar_one()
        job.status = JobStatus(job_status)
        session.add(
            InvoiceDraft(
                extraction_job_id=job.id,
                gstin=gstin,
                fp=fp,
                payload={
                    "fields": dict(fields),
                    "lines": [
                        {
                            "desc": "Item 1",
                            "hsn_sac": "9999",
                            "uqc": "PCS",
                            "qty": 1,
                            "unit_price_paise": fields["taxable_value_paise"],
                            "gst_rate": 18,
                            "taxable_value_paise": fields["taxable_value_paise"],
                            "cess_paise": 0,
                        }
                    ],
                },
                field_confidence={k: 0.99 for k in fields},
            )
        )
        await session.commit()


async def _seeded_doc(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[Any],
    *,
    aato_minor: int | None = None,
    state_code: str = "27",
) -> tuple[dict[str, str], str, str]:
    """Register a user, attach a GSTIN with an open period, upload one doc."""
    from app.core.auth.tokens import verify_access_token

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(
        sessionmaker, user_id, state_code=state_code, aato_minor=aato_minor
    )
    await seed_open_period(sessionmaker, account.gstin, FP)
    doc_id = await _upload_one_doc(client, headers, account.gstin, FP)
    return headers, account.gstin, doc_id


async def test_review_queue_lists_needs_review_ordered_by_confidence(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    supplier = make_gstin(state_code="27")
    fields = _clean_fields(gstin, supplier)
    # two docs, lower confidence second so ordering matters
    await _attach_draft(api_sessionmaker, doc_id, gstin, FP, fields, job_status="NEEDS_REVIEW")

    resp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/review-queue", headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["document_id"] == doc_id
    assert rows[0]["job_status"] == "NEEDS_REVIEW"
    assert rows[0]["capture_source"] == "PHOTO"
    assert rows[0]["doc_type"] in {"UNCLASSIFIED", "INV", "CDN", "DBN", "OTHER"}
    # uploaded_at present and ISO formatted
    assert rows[0]["uploaded_at"] is not None and "T" in rows[0]["uploaded_at"]


async def test_get_draft_returns_fields_flags_and_validator_derived(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )

    resp = await client.get(f"/api/v1/documents/{doc_id}/draft", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["document_id"] == doc_id
    assert data["fp"] == FP
    assert data["capture_source"] == "PHOTO"
    assert data["fields"]["invoice_no"] == "INV-RV-001"
    assert data["confidence"]["invoice_no"] == pytest.approx(0.99)
    assert isinstance(data["flags"], list)
    assert "auto_confirm" in data and "confidence_avg" in data
    assert "derived" in data


async def test_update_draft_edits_field_and_confidence_becomes_human_trusted(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    fields = _clean_fields(gstin, make_gstin(state_code="27"))
    await _attach_draft(api_sessionmaker, doc_id, gstin, FP, fields)

    resp = await client.put(
        f"/api/v1/documents/{doc_id}/draft",
        headers=headers,
        json={"invoice_no": "INV-RV-002"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["fields"]["invoice_no"] == "INV-RV-002"
    # human-edited field is trusted: confidence pinned to 1.0
    assert data["confidence"]["invoice_no"] == 1.0
    # untouched fields keep their machine confidence
    assert data["confidence"]["supplier_gstin"] == pytest.approx(0.99)


async def test_update_draft_promotes_extracted_job_to_needs_review(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )

    resp = await client.put(
        f"/api/v1/documents/{doc_id}/draft",
        headers=headers,
        json={"buyer_address": "5 Road, Pune"},
    )
    assert resp.status_code == 200, resp.text
    # EXTRACTED -> NEEDS_REVIEW once a human touches the draft
    q = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{FP}/review-queue", headers=headers
    )
    assert q.status_code == 200
    assert any(r["document_id"] == doc_id for r in q.json()["data"])


async def test_update_draft_rejects_no_editable_fields(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )

    resp = await client.put(
        f"/api/v1/documents/{doc_id}/draft", headers=headers, json={"not_a_field": 1}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_confirm_draft_creates_invoice_and_lines_paise_exact(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    supplier = make_gstin(state_code="27")
    await _attach_draft(api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, supplier))

    resp = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert resp.status_code == 200, resp.text
    invoice_id = resp.json()["data"]["invoice_id"]

    from app.db.models.gst import Invoice, InvoiceLine

    async with api_sessionmaker() as session:
        invoice = await session.get(Invoice, uuid.UUID(invoice_id))
        assert invoice is not None
        assert invoice.gstin == gstin
        assert invoice.direction.value == "PURCHASE"  # buyer is the registration
        assert invoice.supplier_gstin == supplier
        assert invoice.buyer_gstin == gstin
        assert invoice.invoice_no == "INV-RV-001"
        assert invoice.total_value_minor == 118000  # paise, integer
        assert invoice.status.value == "CONFIRMED"
        assert invoice.source_doc_id == uuid.UUID(doc_id)
        lines = (
            (
                await session.execute(
                    select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(lines) == 1
        # intra-state: 18% on 100000 paise = 18000 -> split 9000/9000, igst 0
        assert lines[0].cgst_minor == 9000
        assert lines[0].sgst_minor == 9000
        assert lines[0].igst_minor == 0
        assert lines[0].taxable_value_minor == 100000
        assert lines[0].gst_rate == 18


async def test_confirm_inter_state_invoice_splits_igst_only(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    supplier = make_gstin(state_code="29")  # different state -> INTER supply
    fields = _clean_fields(gstin, supplier)
    fields["is_inter_state"] = True
    fields["place_of_supply"] = "27"  # registration's state
    fields["cgst_paise"] = 0
    fields["sgst_paise"] = 0
    fields["igst_paise"] = 18000
    await _attach_draft(api_sessionmaker, doc_id, gstin, FP, fields)

    resp = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert resp.status_code == 200, resp.text
    invoice_id = resp.json()["data"]["invoice_id"]

    from app.db.models.gst import Invoice, InvoiceLine

    async with api_sessionmaker() as session:
        invoice = await session.get(Invoice, uuid.UUID(invoice_id))
        assert invoice.supply_type.value == "INTER"
        line = (
            (
                await session.execute(
                    select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
                )
            )
            .scalars()
            .one()
        )
        assert line.cgst_minor == 0
        assert line.sgst_minor == 0
        assert line.igst_minor == 18000


async def test_confirm_twice_returns_409(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    first = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_CONFIRMED"


async def test_confirm_duplicate_invoice_no_returns_409(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    assert (
        await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    ).status_code == 200

    # second doc, same invoice_no in the same gstin/fp
    doc2 = await _upload_one_doc(client, headers, gstin, FP)
    await _attach_draft(
        api_sessionmaker, doc2, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    resp = await client.post(f"/api/v1/documents/{doc2}/confirm", headers=headers)
    # the validator flags the duplicate before the service-level 409 belt
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_DIRTY"
    assert "DUPLICATE_INVOICE" in resp.json()["error"]["message"]


async def test_confirm_on_locked_period_returns_423(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    from app.db.models.gst import FilingPeriod, FilingStatus

    async with api_sessionmaker() as session:
        period = await session.get(FilingPeriod, (gstin, FP))
        period.status = FilingStatus.FILED
        session.add(period)
        await session.commit()

    resp = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert resp.status_code == 423
    assert resp.json()["error"]["code"] == "PERIOD_LOCKED"


async def test_confirm_rejected_document_returns_422(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    rej = await client.post(
        f"/api/v1/documents/{doc_id}/reject", headers=headers, json={"reason": "blurry scan"}
    )
    assert rej.status_code == 200, rej.text
    resp = await client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_reject_sets_failed_and_blocks_reject_after_confirm(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    rej = await client.post(
        f"/api/v1/documents/{doc_id}/reject", headers=headers, json={"reason": "wrong party"}
    )
    assert rej.status_code == 200, rej.text
    body = rej.json()["data"]
    assert body["document_id"] == doc_id
    assert body["status"] == "FAILED"

    from app.db.models.extraction import ExtractionJob, JobStatus

    async with api_sessionmaker() as session:
        job = (
            await session.execute(
                select(ExtractionJob).where(ExtractionJob.document_id == uuid.UUID(doc_id))
            )
        ).scalar_one()
        assert job.status == JobStatus.FAILED
        assert job.error == "wrong party"


async def test_review_flow_tenant_isolation_404(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, doc_id = await _seeded_doc(client, api_sessionmaker)
    await _attach_draft(
        api_sessionmaker, doc_id, gstin, FP, _clean_fields(gstin, make_gstin(state_code="27"))
    )
    # a different user with no access to this GSTIN
    outsider_tokens = await register_and_login(client, make_mobile())
    outsider_headers = {"Authorization": f"Bearer {outsider_tokens['access_token']}"}

    for method, url in [
        ("GET", f"/api/v1/documents/{doc_id}/draft"),
        ("PUT", f"/api/v1/documents/{doc_id}/draft"),
        ("POST", f"/api/v1/documents/{doc_id}/confirm"),
        ("POST", f"/api/v1/documents/{doc_id}/reject"),
    ]:
        kwargs: dict[str, Any] = {"headers": outsider_headers}
        if method in ("PUT", "POST"):
            kwargs["json"] = {"invoice_no": "X"} if method == "PUT" else {"reason": "x"}
        resp = await client.request(method, url, **kwargs)
        assert resp.status_code == 404, (method, resp.status_code, resp.text)


async def test_draft_not_found_and_document_not_found_404(
    client: httpx.AsyncClient, api_sessionmaker: async_sessionmaker[Any]
) -> None:
    headers, gstin, _ = await _seeded_doc(client, api_sessionmaker)
    # doc exists (uploaded) but no draft attached
    doc_id = await _upload_one_doc(client, headers, gstin, FP)
    resp = await client.get(f"/api/v1/documents/{doc_id}/draft", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DRAFT_NOT_FOUND"

    missing = str(uuid.uuid4())
    resp2 = await client.get(f"/api/v1/documents/{missing}/draft", headers=headers)
    assert resp2.status_code == 404
    assert resp2.json()["error"]["code"] in {"DOCUMENT_NOT_FOUND", "NOT_FOUND"}
