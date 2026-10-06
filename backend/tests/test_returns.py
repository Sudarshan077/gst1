import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.routers.returns import file_gstr4, prepare_gstr4
from app.core.access import GstinAccess


@pytest.mark.asyncio
async def test_prepare_gstr4():
    # Placeholder test for prepare_gstr4
    session = AsyncMock()
    access = AsyncMock(spec=GstinAccess)
    result = await prepare_gstr4("27ABCDE1234F1Z5", "032027", access, session)
    assert result["success"] is True

@pytest.mark.asyncio
async def test_file_gstr4():
    session = AsyncMock()
    access = AsyncMock(spec=GstinAccess)
    # mock session.get returning None
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()

    result = await file_gstr4("27ABCDE1234F1Z5", "032027", access, session, uuid.uuid4())
    assert result["success"] is True
    assert result["data"]["status"] == "FILED"
