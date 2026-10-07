import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.db.models.core import User
from app.services.notifications import _route_to_channels


@pytest.mark.asyncio
async def test_notification_routing_preferences() -> None:
    # Setup
    session = AsyncMock()
    user_id: str = str(uuid.uuid4())
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        full_name="Test User",
        notification_preferences={"email": True, "whatsapp": False}
    )

    # Mock session.get to return our user
    session.get.return_value = user

    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_email,
    ):

        # Test 1: Email enabled → email fires.
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_called_once()

        mock_email.reset_mock()

        # Test 2: Email disabled → nothing fires (WhatsApp is stubbed/config-gated).
        user.notification_preferences = {"email": False, "whatsapp": True}
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_not_called()

        mock_email.reset_mock()

        # Test 3: Both enabled → email fires (WhatsApp remains stubbed/config-gated).
        user.notification_preferences = {"email": True, "whatsapp": True}
        await _route_to_channels(session, user_id, "test_event", {"data": "test"})

        mock_email.assert_called_once()
