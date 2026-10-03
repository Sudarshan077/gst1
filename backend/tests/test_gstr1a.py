import io

import httpx
import pytest
from app.db.models.gst import Gstr1aAmendment
from PIL import Image
from sqlalchemy import select

from tests.v4_helpers import seed_account, seed_open_period


@pytest.mark.asyncio
async def test_gstr1a_amendments_and_locking(client: httpx.AsyncClient, api_sessionmaker):
    tokens, account = await seed_account(client, api_sessionmaker)
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Generate GSTR-1 export
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/generate",
        headers=headers
    )
    assert resp.status_code == 200, resp.text
    export_id = resp.json()["data"]["export_id"]

    # File return (locks period)
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/filed",
        headers=headers
    )
    assert resp.status_code == 200, resp.text

    # Attempt direct document upload/mutation on filed period should return 423
    img = Image.new("RGB", (1, 1), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    files = {"files": ("test2.png", buf.getvalue(), "image/png")}
    data = {"capture_source": "PHOTO"}
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        files=files,
        data=data
    )
    assert resp.status_code == 423, f"Expected 423 on locked period mutation, got {resp.status_code}: {resp.text}"

    # Submit GSTR-1A amendment delta
    amendment_payload = {
        "amendments": [
            {
                "field_deltas": {"taxable_value_paise": 50000},
                "reason": "Value correction for outward supply"
            }
        ]
    }
    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1a",
        headers=headers,
        json=amendment_payload
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["amendments"]) == 1
    assert data["status"] == "AMENDED"

    # Verify delta record created in DB and target_export_id linked correctly
    async with api_sessionmaker() as session:
        amendments = (await session.execute(
            select(Gstr1aAmendment).where(Gstr1aAmendment.target_export_id == export_id)
        )).scalars().all()
        assert len(amendments) == 1
        assert amendments[0].reason == "Value correction for outward supply"
        assert amendments[0].field_deltas == {"taxable_value_paise": 50000}
