from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.gst import Notification
from app.db.models.core import User

async def create_notification(
    session: AsyncSession,
    user_id: str,
    gstin: str | None,
    n_type: str,
    payload: dict,
):
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

async def _route_to_channels(session: AsyncSession, user_id: str, n_type: str, payload: dict):
    """Route notification to email/WhatsApp based on user preferences."""
    # TODO: Fetch user preferences from DB (need to add prefs to User model)
    # For now, default to email if user has email.
    
    user = await session.get(User, user_id)
    if not user:
        return

    # Email
    if user.email:
        await _send_email(user.email, n_type, payload)
    
    # WhatsApp (Stubbed/config-gated)
    # if settings.WHATSAPP_ENABLED:
    #    await _send_whatsapp(user.mobile, n_type, payload)

async def _send_email(email: str, n_type: str, payload: dict):
    """Placeholder for email service."""
    # Using real email backend is out of scope for this task's core logic
    print(f"Sending email to {email}: {n_type} - {payload}")

async def _send_whatsapp(mobile: str, n_type: str, payload: dict):
    """Placeholder for WhatsApp service."""
    print(f"Sending WhatsApp to {mobile}: {n_type} - {payload}")
