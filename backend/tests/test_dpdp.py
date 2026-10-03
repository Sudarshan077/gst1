import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.services.dpdp import export_data, request_erasure

@pytest.mark.asyncio
async def test_dpdp_export_and_erasure():
    session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_res.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_res
    user_id = uuid.uuid4()
    gstin = "29AAAAA0000A1Z5"
    
    res = await export_data(session, user_id, gstin)
    assert res["success"] is True
    assert "request_id" in res["data"]
    
    res2 = await request_erasure(session, user_id, gstin)
    assert res2["success"] is True
    assert "request_id" in res2["data"]
