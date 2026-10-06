"""Direct service-layer regression for the review/confirm flow (review.py).

The API-driven suites (test_review_flow.py) verify the full request path;
this suite calls the service functions directly. On this Windows/CPython-3.11
host the coverage CTracer under-attributes lines executed downstream of a
suspended async-generator FastAPI dependency (get_session yield), so the
direct-call suites exist both as regression depth for the service layer and
to make the coverage gate reflect the code the suite genuinely exercises.

Money is integer paise everywhere; GSTINs are mod-36 checksum-valid
synthetic fixtures via tests/gstin_fixtures.make_gstin.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.gstin_fixtures import make_gstin

pytestmark = pytest.mark.asyncio

FP = "092026"


def _clean_fields(reg_gstin: str, supplier_gstin: str) -> dict[str, Any]:
    """Validator-clean intra-state purchase field set (integer paise)."""
    taxable = 100000
    cgst = sgst = 9000
    return {
        "supplier_gstin": supplier_gstin,
        "buyer_gstin": reg_gstin,
        "invoice_no": "INV-DS-001",
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


async def _seed_doc_with_draft(
    sessionmaker: async_sessionmaker[Any],
    *,
    fields: dict[str, Any] | None = None,
    job_status: str = "EXTRACTED",
    with_period: bool = True,
    is_inter_state: bool = False,
) -> tuple[str, str, uuid.UUID]:
    """Seed account+period+document+job+draft directly; return (gstin, doc_id, user_id)."""
    from app.db import base as app_db_base
    from app.db.models.core import AccessRole, FilingScheme, GstAccount, User, UserGstAccess
    from app.db.models.extraction import (
        CaptureSource,
        Document,
        ExtractionJob,
        InvoiceDraft,
        JobStatus,
    )
    from app.db.models.gst import FilingPeriod, FilingStatus

    app_db_base.all_models()
    gstin = make_gstin(state_code="27")
    supplier = make_gstin(state_code="29" if is_inter_state else "27")
    if fields is None:
        fields = _clean_fields(gstin, supplier)
        if is_inter_state:
            fields["is_inter_state"] = True
            fields["cgst_paise"] = 0
            fields["sgst_paise"] = 0
            fields["igst_paise"] = 18000
    # buyer is always the registration for purchase drafts
    fields = dict(fields)
    fields["buyer_gstin"] = gstin
    async with sessionmaker() as session:
        user = User(mobile="9" + uuid.uuid4().hex[:9], full_name="DS Co")
        session.add(user)
        await session.flush()
        session.add(
            GstAccount(gstin=gstin, legal_name="DS Co", pan=gstin[2:12], state_code="27")
        )
        session.add(UserGstAccess(gstin=gstin, user_id=user.id, role=AccessRole.ADMIN))
        if with_period:
            session.add(
                FilingPeriod(
                    gstin=gstin,
                    fp=FP,
                    scheme_snapshot=FilingScheme.REGULAR_MONTHLY.value,
                    status=FilingStatus.OPEN,
                )
            )
        doc = Document(
            id=uuid.uuid4(),
            gstin=gstin,
            fp=FP,
            capture_source=CaptureSource.PHOTO,
            doc_type="INV",
            minio_key=f"{gstin}/{FP}/ds.png",
            sha256=uuid.uuid4().hex,
            bytes=100,
            page_count=1,
            uploaded_by=user.id,
        )
        job = ExtractionJob(document_id=doc.id, status=JobStatus(job_status))
        session.add(doc)
        session.add(job)
        await session.flush()
        session.add(
            InvoiceDraft(
                extraction_job_id=job.id,
                gstin=gstin,
                fp=FP,
                payload={
                    "fields": dict(fields),
                    "lines": [
                        {
                            "desc": "Item 1",
                            "hsn_sac": "9999",
                            "uqc": "PCS",
                            "qty": 1,
                            "unit_price_paise": 100000,
                            "gst_rate": 18,
                            "taxable_value_paise": 100000,
                            "cess_paise": 0,
                        }
                    ],
                },
                field_confidence={k: 0.99 for k in fields},
            )
        )
        await session.commit()
        user_id = user.id
    return gstin, str(doc.id), user_id


def _access(gstin: str, user_id: uuid.UUID, role: str = "ADMIN") -> Any:
    from app.core.access import AccessRole, GstinAccess

    return GstinAccess(
        gstin=gstin,
        role=AccessRole(role),
        user_id=user_id,
        legal_name="DS Co",
        pan=gstin[2:12],
    )


async def test_service_review_queue_and_get_draft(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.services.review import get_draft, get_review_queue

    gstin, doc_id, user_id = await _seed_doc_with_draft(
        api_sessionmaker, job_status="NEEDS_REVIEW"
    )
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        queue = await get_review_queue(session, access, FP)
        assert len(queue) == 1
        assert queue[0]["document_id"] == doc_id
        assert queue[0]["job_status"] == "NEEDS_REVIEW"
        assert queue[0]["doc_type"] == "INV"

        draft = await get_draft(session, uuid.UUID(doc_id), access)
        assert draft["document_id"] == doc_id
        assert draft["fields"]["invoice_no"] == "INV-DS-001"
        assert draft["confidence"]["invoice_no"] == pytest.approx(0.99)
        assert "flags" in draft and "derived" in draft


async def test_service_update_draft_and_promote_job(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.db.models.extraction import ExtractionJob, JobStatus
    from app.services.review import update_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        envelope = await update_draft(
            session,
            uuid.UUID(doc_id),
            access,
            user_id,
            {"invoice_no": "INV-DS-002", "buyer_name": "Acme"},
        )
        assert envelope["fields"]["invoice_no"] == "INV-DS-002"
        assert envelope["confidence"]["invoice_no"] == 1.0
        job = (
            await session.execute(
                select(ExtractionJob).where(
                    ExtractionJob.document_id == uuid.UUID(doc_id)
                )
            )
        ).scalar_one()
        assert job.status == JobStatus.NEEDS_REVIEW


async def test_service_update_draft_no_editable_fields_raises(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import update_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await update_draft(
                session, uuid.UUID(doc_id), access, user_id, {"nope": 1}
            )
        assert exc.value.status_code == 422


async def test_service_confirm_draft_writes_invoice_lines(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.db.models.gst import Invoice, InvoiceLine
    from app.services.review import confirm_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        result = await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        invoice_id = uuid.UUID(result["invoice_id"])

        invoice = await session.get(Invoice, invoice_id)
        assert invoice is not None
        assert invoice.direction.value == "PURCHASE"
        assert invoice.total_value_minor == 118000
        assert invoice.status.value == "CONFIRMED"
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
        assert (lines[0].cgst_minor, lines[0].sgst_minor, lines[0].igst_minor) == (
            9000,
            9000,
            0,
        )
        assert lines[0].taxable_value_minor == 100000


async def test_service_confirm_inter_state_igst_only(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.db.models.gst import Invoice, InvoiceLine
    from app.services.review import confirm_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(
        api_sessionmaker, is_inter_state=True
    )
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        result = await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        invoice = await session.get(Invoice, uuid.UUID(result["invoice_id"]))
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
        assert (line.cgst_minor, line.sgst_minor, line.igst_minor) == (0, 0, 18000)


async def test_service_confirm_twice_raises_409(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import confirm_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        assert exc.value.status_code == 409


async def test_service_confirm_locked_period_raises_423(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.db.models.gst import FilingPeriod, FilingStatus
    from app.services.review import confirm_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    async with api_sessionmaker() as session:
        period = await session.get(FilingPeriod, (gstin, FP))
        period.status = FilingStatus.FILED
        session.add(period)
        await session.commit()

    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        assert exc.value.status_code == 423
        assert exc.value.code == "PERIOD_LOCKED"


async def test_service_confirm_without_period_raises_404(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import confirm_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(
        api_sessionmaker, with_period=False
    )
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        assert exc.value.status_code == 404
        assert exc.value.code == "PERIOD_NOT_FOUND"


async def test_service_confirm_rejected_doc_raises_422(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import confirm_draft, reject_document

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        await reject_document(session, uuid.UUID(doc_id), access, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
        assert exc.value.status_code == 422


async def test_service_reject_sets_failed(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.db.models.extraction import ExtractionJob, JobStatus
    from app.services.review import reject_document

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        result = await reject_document(
            session, uuid.UUID(doc_id), access, user_id, reason="blurry"
        )
        assert result["status"] == "FAILED"
        job = (
            await session.execute(
                select(ExtractionJob).where(
                    ExtractionJob.document_id == uuid.UUID(doc_id)
                )
            )
        ).scalar_one()
        assert job.status == JobStatus.FAILED
        assert job.error == "blurry"


async def test_service_reject_after_confirm_raises_409(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import confirm_draft, reject_document

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        await confirm_draft(session, uuid.UUID(doc_id), access, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await reject_document(session, uuid.UUID(doc_id), access, user_id)
        assert exc.value.status_code == 409


async def test_service_cross_tenant_access_raises_404(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import get_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    other_gstin = make_gstin(state_code="27")
    outsider = uuid.uuid4()
    wrong_access = _access(other_gstin, outsider)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await get_draft(session, uuid.UUID(doc_id), wrong_access)
        assert exc.value.status_code == 404
        assert exc.value.code == "DOCUMENT_NOT_FOUND"


async def test_service_missing_draft_raises_404(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import get_draft

    gstin, doc_id, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        # doc + job but no draft -> DRAFT_NOT_FOUND
        from app.db.models.extraction import (
            CaptureSource,
            Document,
            ExtractionJob,
            JobStatus,
        )

        orphan = Document(
            id=uuid.uuid4(),
            gstin=gstin,
            fp=FP,
            capture_source=CaptureSource.PHOTO,
            doc_type="INV",
            minio_key=f"{gstin}/{FP}/orphan.png",
            sha256=uuid.uuid4().hex,
            bytes=10,
            page_count=1,
        )
        session.add(orphan)
        session.add(ExtractionJob(document_id=orphan.id, status=JobStatus.QUEUED))
        await session.commit()
        with pytest.raises(ServiceError) as exc:
            await get_draft(session, orphan.id, access)
        assert exc.value.code == "DRAFT_NOT_FOUND"


async def test_service_missing_document_raises_404(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    from app.api.errors import ServiceError
    from app.services.review import get_draft

    gstin, _, user_id = await _seed_doc_with_draft(api_sessionmaker)
    access = _access(gstin, user_id)
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await get_draft(session, uuid.uuid4(), access)
        assert exc.value.status_code == 404


async def test_direction_for_b2c_edge_and_mismatch(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """_direction_for unit branches: SALES/PURCHASE/B2C edge + no-match 422."""
    from app.api.errors import ServiceError
    from app.services.review import _direction_for

    reg = make_gstin(state_code="27")
    other = make_gstin(state_code="27")

    class F:
        supplier_gstin = reg
        buyer_gstin = other

    assert _direction_for(F(), reg).value == "SALES"

    class G:
        supplier_gstin = other
        buyer_gstin = reg

    assert _direction_for(G(), reg).value == "PURCHASE"

    class H:  # B2C edge: buyer absent, supplier is someone else
        supplier_gstin = other
        buyer_gstin = None

    assert _direction_for(H(), reg).value == "PURCHASE"

    class X:  # references neither party
        supplier_gstin = None
        buyer_gstin = None

    with pytest.raises(ServiceError) as exc:
        _direction_for(X(), reg)
    assert exc.value.status_code == 422


async def test_compute_line_taxes_rounding_half_up(
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """_compute_line_taxes: HALF_UP rounding, dict + model inputs, inter/intra."""
    from app.extraction.models import ExtractedLine
    from app.services.review import _compute_line_taxes

    # 999 paise taxable at 5% -> 49.95 -> HALF_UP 50; intra: 25/25
    cgst, sgst, igst = _compute_line_taxes({"taxable_value_paise": 999, "gst_rate": 5}, False)
    assert (cgst, sgst, igst) == (25, 25, 0)

    # odd total tax splits without losing a paisa: 75 -> 38/37
    cgst, sgst, igst = _compute_line_taxes({"taxable_value_paise": 1500, "gst_rate": 5}, False)
    assert (cgst, sgst, igst) == (38, 37, 0)

    # inter: all tax to IGST
    cgst, sgst, igst = _compute_line_taxes({"taxable_value_paise": 100000, "gst_rate": 18}, True)
    assert (cgst, sgst, igst) == (0, 0, 18000)

    # ExtractedLine model input path
    line = ExtractedLine(desc="x", taxable_value_paise=100000, gst_rate=18)
    assert _compute_line_taxes(line, True) == (0, 0, 18000)
