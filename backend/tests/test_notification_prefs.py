import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.db.models.core import User
from app.services.notifications import _route_to_channels


@pytest.mark.asyncio
async def test_notification_routing_preferences():
    # Setup
    session = AsyncMock()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="test@example.com",
        mobile="1234567890",
        full_name="Test User",
        notification_preferences={"email": True, "whatsapp": False}
    )

    # Mock session.get to return our user
    session.get.return_value = user

    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_email,
        patch("app.services.notifications._send_whatsapp", new_callable=AsyncMock) as mock_whatsapp,
    ):

        # Test 1: Email enabled, WhatsApp disabled
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_called_once()
        mock_whatsapp.assert_not_called()

        mock_email.reset_mock()
        mock_whatsapp.reset_mock()

        # Test 2: Email disabled, WhatsApp enabled
        user.notification_preferences = {"email": False, "whatsapp": True}
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_not_called()
        mock_whatsapp.assert_called_once()

        mock_email.reset_mock()
        mock_whatsapp.reset_mock()

        # Test 3: Both enabled
        user.notification_preferences = {"email": True, "whatsapp": True}
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_called_once()
        mock_whatsapp.assert_called_once()
