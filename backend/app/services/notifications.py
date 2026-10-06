from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import User
from app.db.models.gst import Notification


async def create_notification(
    session: AsyncSession,
    user_id: str,
    gstin: str | None,
    n_type: str,
    payload: dict[str, Any],
) -> Notification:
    """Create in-app notification and route to channels."""
    notification = Notification(
        user_id=user_id,
        gstin=gstin,
        type=n_type,
        payload=payload,
    )
    session.add(notification)

    # In-app is always created (above).
    # Now route to other channels based on preferences.
    # Note: WhatsApp stubbed/config-gated.

    await _route_to_channels(session, user_id, n_type, payload)
    return notification


async def _route_to_channels(
    session: AsyncSession,
    user_id: str,
    n_type: str,
    payload: dict[str, Any],
) -> None:
    """Route notification to email/WhatsApp based on user preferences."""
    user = await session.get(User, user_id)
    if not user:
        return

    prefs = user.notification_preferences or {}

    # Email (default enabled)
    if user.email and prefs.get("email", True):
        await _send_email(user.email, n_type, payload)

    # WhatsApp (default disabled)
    if user.mobile and prefs.get("whatsapp", False):
        await _send_whatsapp(user.mobile, n_type, payload)


async def _send_email(email: str, n_type: str, payload: dict[str, Any]) -> None:
    """Placeholder for email service."""
    # Using real email backend is out of scope for this task's core logic
    print(f"Sending email to {email}: {n_type} - {payload}")


async def _send_whatsapp(mobile: str, n_type: str, payload: dict[str, Any]) -> None:
    """Placeholder for WhatsApp service."""
    print(f"Sending WhatsApp to {mobile}: {n_type} - {payload}")
