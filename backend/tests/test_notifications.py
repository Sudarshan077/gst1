import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.services.returns.deadline import check_and_fire_reminders
from app.db.models.gst import FilingPeriod, FilingStatus

@pytest.mark.asyncio
async def test_check_and_fire_reminders():
    # Setup
    session = AsyncMock()
    
    today = date.today()
    due_date = today + timedelta(days=3)
    
    period = FilingPeriod(
        gstin="27ABCDE1234F1Z5",
        fp="042026",
        gstr1_due_date=due_date,
        status=FilingStatus.OPEN
    )
    
    # Create a mock result for execute
    mock_result = MagicMock()
    # Chain: execute -> scalar -> all
    mock_result.scalars.return_value.all.return_value = [period]
    
    # UserGstAccess call
    mock_access_result = MagicMock()
    mock_access_result.scalars.return_value.all.return_value = []
    
    # Existing notification call
    mock_notif_result = MagicMock()
    mock_notif_result.scalar_one_or_none.return_value = None
    
    # Set side_effect to handle the sequence of calls
    # 1. FilingPeriods, 2. UserGstAccess, 3. ExistingNotification
    session.execute.side_effect = [mock_result, mock_access_result, mock_notif_result]
    
    fired_count = await check_and_fire_reminders(session)
    
    # With empty access list, no notification should be fired
    assert fired_count == 0
