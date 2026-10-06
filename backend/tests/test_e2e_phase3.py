import io
import time

import httpx
import pytest
from app.db.models.extraction import ExtractionJob, InvoiceDraft, JobStatus
from PIL import Image
from sqlalchemy import select

from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account, seed_open_period


@pytest.mark.asyncio
async def test_five_client_month_end(client: httpx.AsyncClient, api_sessionmaker):
    start_time = time.perf_counter()
    num_clients = 5
    fp = "092026"

    for i in range(num_clients):
        # 1. Setup
        tokens, account = await seed_account(client, api_sessionmaker, legal_name=f"Client {i}")
        gstin = account.gstin
        await seed_open_period(api_sessionmaker, gstin, fp)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # 2. Upload (Mock)
        img = Image.new("RGB", (1, 1), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        files = {"files": ("test.png", buf.getvalue(), "image/png")}
        data = {"capture_source": "PHOTO"}
        resp = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            files=files,
            data=data
        )
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["data"]["id"]

        # 3. Extract + Confirm
        async with api_sessionmaker() as session:
            job = (await session.execute(
                select(ExtractionJob).where(ExtractionJob.document_id == doc_id)
            )).scalar_one()
            job.status = JobStatus.EXTRACTED

            draft = InvoiceDraft(
                extraction_job_id=job.id,
                gstin=gstin,
                fp=fp,
                payload={
                    "fields": {
                        "supplier_gstin": make_gstin(state_code="27"),
                        "buyer_gstin": gstin,
                        "invoice_no": f"INV-{i}-001",
                        "invoice_date": "2026-09-01",
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
                    "lines": [],
                },
            )
            session.add(draft)
            await session.commit()

        resp = await client.post(
            f"/api/v1/documents/{doc_id}/confirm",
            headers=headers
        )
        assert resp.status_code == 200, resp.text

        # 4. Prepare
        resp = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/prepare",
            headers=headers
        )
        assert resp.status_code == 200, resp.text

        # 5. Generate
        resp = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/generate",
            headers=headers
        )
        assert resp.status_code == 200, resp.text

        # 6. File
        resp = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/filed",
            headers=headers
        )
        assert resp.status_code == 200, resp.text

        # 7. Audit Trail Check
        resp = await client.get(f"/api/v1/gst-accounts/{gstin}/audit", headers=headers)
        assert resp.status_code == 200, resp.text
        audit_data = resp.json()["data"]
        assert len(audit_data) >= 4, f"Expected >= 4, got {len(audit_data)}. Audit: {audit_data}"

    end_time = time.perf_counter()
    duration = end_time - start_time
    assert duration < 1800, f"Took {duration} seconds, expected < 1800"
