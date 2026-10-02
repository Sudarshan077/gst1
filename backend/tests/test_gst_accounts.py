import pytest
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker, make_mobile, register_and_login
from tests.gstin_fixtures import make_gstin


# Use pytest-asyncio to run async tests
@pytest.mark.asyncio
async def test_gst_accounts_crud(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    # 1. Create user and log in
    mobile = make_mobile()
    auth_data = await register_and_login(client, mobile)
    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create GST Account
    gstin = make_gstin()
    response = await client.post(
        "/api/v1/gst-accounts",
        headers=headers,
        json={
            "gstin": gstin,
            "legal_name": "Test Company",
            "trade_name": "Test Trade Name",
        },
    )
    assert response.status_code == 200

    # 3. List
    response = await client.get("/api/v1/gst-accounts", headers=headers)
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1

    # 4. Get
    response = await client.get(f"/api/v1/gst-accounts/{gstin}", headers=headers)
    assert response.status_code == 200

    # 5. Patch
    response = await client.patch(
        f"/api/v1/gst-accounts/{gstin}", headers=headers, json={"trade_name": "New Trade Name"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["trade_name"] == "New Trade Name"
