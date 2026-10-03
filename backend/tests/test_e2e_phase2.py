import pytest
import httpx
import io
import asyncio
from PIL import Image
from datetime import date
from app.db.models.gst import FilingStatus
from tests.v4_helpers import seed_account, seed_open_period
from tests.gstin_fixtures import make_gstin

@pytest.mark.asyncio
async def test_full_return_journey(client: httpx.AsyncClient, api_sessionmaker):
    # 1. Setup
    tokens, account = await seed_account(client, api_sessionmaker)
    gstin = account.gstin
    fp = "092026"
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
    
    # 3. Update existing Job and add Draft
    async with api_sessionmaker() as session:
        from app.db.models.extraction import ExtractionJob, JobStatus, InvoiceDraft
        from tests.gstin_fixtures import make_gstin
        from sqlalchemy import select
        
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
                    "invoice_no": "INV-001",
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
        )
        session.add(draft)
        await session.commit()
    
    resp = await client.post(
        f"/api/v1/documents/{doc_id}/confirm",
        headers=headers
    )
    assert resp.status_code == 200, resp.text
    
    # 4. Prepare
    url = f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/prepare"
    print(f"URL: {url}")
    resp = await client.post(url, headers=headers)
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
    
    # 7. 1A
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1a",
        headers=headers,
        json={"amendments": []} # Simplified
    )
    assert resp.status_code == 200, resp.text
