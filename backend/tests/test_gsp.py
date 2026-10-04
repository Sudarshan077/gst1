
import pytest
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker, make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin


@pytest.mark.asyncio
async def test_gsp_filing_and_2b_fetch(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    # 1. Setup
    auth_data = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    gstin = make_gstin()
    fp = "092026"

    # Create GST Account
    await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={"gstin": gstin, "legal_name": "GSP Test Company"},
    )

    # 2. Test GSP GSTR-1 filing
    url_g1 = f"/api/v1/gst-accounts/{gstin}/months/{fp}/gsp/gstr1/file"
    gstr1_resp = await client.post(url_g1, headers=headers)
    assert gstr1_resp.status_code == 200, gstr1_resp.text
    data = gstr1_resp.json()["data"]
    assert data["status"] == "FILED"
    assert "ref_id" in data
    assert "ack_no" in data

    # 3. Test GSP GSTR-3B filing
    url_3b = f"/api/v1/gst-accounts/{gstin}/months/{fp}/gsp/gstr3b/file"
    gstr3b_resp = await client.post(url_3b, headers=headers)
    assert gstr3b_resp.status_code == 200, gstr3b_resp.text
    data3b = gstr3b_resp.json()["data"]
    assert data3b["status"] == "FILED"
    assert "ref_id" in data3b
    assert "ack_no" in data3b

    # 4. Test GSP GSTR-2B auto-fetch
    url_2b = f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr2b/fetch"
    fetch_resp = await client.post(url_2b, headers=headers)
    assert fetch_resp.status_code == 200, fetch_resp.text
    fetch_data = fetch_resp.json()["data"]
    assert fetch_data["source"] == "GSP_API"
    assert fetch_data["fp"] == fp
    assert fetch_data["gstin"] == gstin
