import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_user
from app.db.models.core import User
from app.db.models.gst import Notification
from app.db.session import get_session

router = APIRouter(prefix="", tags=["notifications"])


def _get_db() -> AsyncIterator[AsyncSession]:
    return get_session()


def _get_user_id() -> Callable[..., Any]:
    """Return the require_user dependency callable itself."""
    return require_user


# FastAPI dependency wiring: _get_db / _get_user_id are callables so B008 is
# satisfied; the actual Depends() call happens at route-registration time.
_DependsDB = Depends(_get_db)
_DependsUser = Depends(_get_user_id)


@router.get("/notifications")
async def list_notifications(
    unread: bool | None = None,
    page: int = 0,
    size: int = 20,
    db: AsyncSession = _DependsDB,
    user_id: uuid.UUID = _DependsUser,
) -> dict[str, Any]:
    """List in-app notifications for the current user."""
    query = select(Notification).where(Notification.user_id == user_id)
    if unread is not None:
        if unread:
            query = query.where(Notification.read_at.is_(None))
        else:
            query = query.where(Notification.read_at.is_not(None))

    query = query.order_by(Notification.created_at.desc())

    total_query = select(Notification).where(Notification.user_id == user_id)
    if unread is not None:
        if unread:
            total_query = total_query.where(Notification.read_at.is_(None))
        else:
            total_query = total_query.where(Notification.read_at.is_not(None))

    total_elements = len((await db.execute(total_query)).scalars().all())

    query = query.offset(page * size).limit(size)
    notifications = (await db.execute(query)).scalars().all()

    content = [
        {
            "id": str(n.id),
            "gstin": n.gstin,
            "type": n.type,
            "payload": n.payload,
            "read_at": n.read_at.isoformat() if n.read_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications
    ]

    return {
        "content": content,
        "page": page,
        "size": size,
        "totalElements": total_elements,
        "last": (page + 1) * size >= total_elements,
    }

@router.post("/notifications/{id}/read")
async def mark_notification_read(
    id: str,
    db: AsyncSession = _DependsDB,
    user_id: uuid.UUID = _DependsUser,
) -> dict[str, Any]:
    """Mark a notification as read."""
    try:
        notif_uuid = uuid.UUID(id)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        ) from err

    notif = await db.get(Notification, notif_uuid)
    if not notif or notif.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if not notif.read_at:
        from datetime import datetime
        notif.read_at = datetime.now(UTC)
        await db.commit()

    return {"success": True}

@router.get("/me/notification-prefs")
async def get_notification_prefs(
    db: AsyncSession = _DependsDB,
    user_id: uuid.UUID = _DependsUser,
) -> dict[str, Any]:
    """Get notification preferences."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"prefs": user.notification_preferences or {}}


@router.patch("/me/notification-prefs")
async def update_notification_prefs(
    body: dict[str, Any],
    db: AsyncSession = _DependsDB,
    user_id: uuid.UUID = _DependsUser,
) -> dict[str, Any]:
    """Update notification preferences (channels per event type)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.notification_preferences = body
    await db.commit()
    return {"success": True, "prefs": user.notification_preferences}
