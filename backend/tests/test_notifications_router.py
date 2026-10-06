"""Tests for the notifications router.

Covers unread/read filter paths and idempotent mark-read in
app/api/routers/notifications.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.auth.tokens import verify_access_token
from app.db.models.gst import Notification
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_mobile, register_and_login

pytestmark = pytest.mark.asyncio


async def test_list_notifications_unread_filter(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        for i in range(3):
            n = Notification(
                user_id=user_id,
                gstin=None,
                type="DEADLINE_REMINDER",
                payload={"msg": f"notification {i}"},
            )
            session.add(n)
        read_n = Notification(
            user_id=user_id,
            gstin=None,
            type="DEADLINE_REMINDER",
            payload={"msg": "read"},
            read_at=datetime.now(UTC),
        )
        session.add(read_n)
        await session.commit()

    response = await client.get("/api/v1/notifications?unread=true", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["totalElements"] == 3
    assert len(data["content"]) == 3
    assert all(n["read_at"] is None for n in data["content"])

    response_read = await client.get("/api/v1/notifications?unread=false", headers=headers)
    assert response_read.status_code == 200
    data_read = response_read.json()
    assert data_read["totalElements"] == 1


async def test_mark_notification_read_idempotent(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])

    async with api_sessionmaker() as session:
        n = Notification(
            user_id=user_id,
            gstin=None,
            type="DEADLINE_REMINDER",
            payload={"msg": "mark me"},
        )
        session.add(n)
        await session.commit()
        await session.refresh(n)
        notif_id = n.id

    r1 = await client.post(f"/api/v1/notifications/{notif_id}/read", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["success"] is True

    r2 = await client.post(f"/api/v1/notifications/{notif_id}/read", headers=headers)
    assert r2.status_code == 200


async def test_update_and_get_notification_prefs(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r1 = await client.patch(
        "/api/v1/me/notification-prefs",
        headers=headers,
        json={"email": False, "whatsapp": True},
    )
    assert r1.status_code == 200
    assert r1.json()["prefs"]["email"] is False

    r2 = await client.get("/api/v1/me/notification-prefs", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["prefs"]["whatsapp"] is True
