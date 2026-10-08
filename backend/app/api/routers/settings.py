"""Settings router — GET/PATCH /me/settings (PHASE8_PRODUCT_COMPLETENESS 8.2).

GET is a read-only aggregate over existing state: the
users.notification_preferences column, TOTP enablement (totp_enabled_at), and
the live Redis refresh-family count ("session info" — the data behind the
future sign-out-everywhere surface).

PATCH /me/settings exists as a *delegating* convenience alias: it forwards the
body to the existing /me/notification-prefs handler (notifications.py), so the
write logic is not duplicated — same validation, same transaction, same audit
surface. GET then reflects whatever state that handler wrote.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.notifications import update_notification_prefs
from app.api.schemas import SettingsEnvelope
from app.core.auth.dependencies import require_user
from app.core.auth.errors import TokenInvalid
from app.core.auth.redis_client import get_redis
from app.core.auth.tokens import REFRESH_TTL_SECONDS
from app.db.models.core import User
from app.db.session import get_session

router = APIRouter(prefix="/me", tags=["settings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

REFRESH_TTL_DAYS = REFRESH_TTL_SECONDS // (24 * 3600)


async def _active_session_count(redis: Redis, user_id: uuid.UUID) -> int:
    """Count live refresh families owned by this user.

    rfam:{family_id} -> user_id (tokens.py). Scanning the small key space and
    matching the user id is the authoritative live-session count under the
    current Redis layout; no DB column exists for it.
    """
    count = 0
    async for key in redis.scan_iter(match="rfam:*", count=500):
        owner = await redis.get(key)
        if owner == str(user_id):
            count += 1
    return count


async def _settings_data(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if user is None:
        # require_user verified a signed JWT; a missing row means the user was
        # deleted between token mint and this call. 401 envelope matches /auth/me.
        raise TokenInvalid("user no longer exists")
    active = await _active_session_count(get_redis(), user_id)
    return {
        "notification_preferences": user.notification_preferences or {},
        "totp_enabled": user.totp_enabled_at is not None,
        "session": {
            "active_sessions": active,
            "refresh_ttl_days": REFRESH_TTL_DAYS,
        },
    }


@router.get("/settings", response_model=SettingsEnvelope)
async def get_settings(session: SessionDep, user_id: UserDep) -> dict[str, object]:
    """GET /me/settings — consolidated account settings (read-only)."""
    return {"success": True, "data": await _settings_data(session, user_id)}


@router.patch("/settings", response_model=SettingsEnvelope)
async def patch_settings(
    body: dict[str, Any], session: SessionDep, user_id: UserDep
) -> dict[str, object]:
    """PATCH /me/settings — delegates to the /me/notification-prefs handler.

    The body IS the notification-prefs payload (channels per event type);
    update_notification_prefs validates and writes it in the same transaction,
    then this route re-reads the aggregate so the response is exactly what
    GET /me/settings would return.
    """
    await update_notification_prefs(body=body, db=session, user_id=user_id)
    return {"success": True, "data": await _settings_data(session, user_id)}
