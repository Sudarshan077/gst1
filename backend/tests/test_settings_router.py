"""Tests for the settings router (PHASE8_PRODUCT_COMPLETENESS 8.2).

GET /me/settings aggregates notification prefs + totp_enabled + session info;
PATCH /me/settings delegates to the /me/notification-prefs handler. These tests
prove the round-trip: patch via /me/settings -> visible via both /me/settings
and /me/notification-prefs.
"""

from __future__ import annotations

import uuid

import pyotp
import pytest
from app.core.auth.tokens import REFRESH_TTL_SECONDS, verify_access_token
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_email, register_and_login

pytestmark = pytest.mark.asyncio


async def test_get_settings_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/me/settings")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_INVALID"


async def test_get_settings_returns_prefs_totp_and_session(
    client: AsyncClient, api_sessionmaker: async_sessionmaker
) -> None:
    tokens = await register_and_login(client, make_email())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])

    # Seed a preference directly so the aggregate reflects the column.
    from app.db.models.core import User as UserModel

    async with api_sessionmaker() as session:
        user = await session.get(UserModel, user_id)
        assert user is not None
        user.notification_preferences = {"email": True, "whatsapp": False}
        await session.commit()

    r = await client.get("/api/v1/me/settings", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["notification_preferences"] == {"email": True, "whatsapp": False}
    assert data["totp_enabled"] is False
    # register_and_login minted exactly one refresh family for this user.
    assert data["session"]["active_sessions"] == 1
    assert data["session"]["refresh_ttl_days"] == REFRESH_TTL_SECONDS // (24 * 3600)


async def test_patch_settings_round_trips_through_prefs(
    client: AsyncClient,
) -> None:
    tokens = await register_and_login(client, make_email())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # PATCH via /me/settings (the delegating aggregate route).
    r_patch = await client.patch(
        "/api/v1/me/settings",
        headers=headers,
        json={"email": False, "whatsapp": True},
    )
    assert r_patch.status_code == 200
    patched = r_patch.json()["data"]
    assert patched["notification_preferences"] == {"email": False, "whatsapp": True}
    assert patched["totp_enabled"] is False
    assert patched["session"]["active_sessions"] >= 1

    # The existing /me/notification-prefs handler is the single writer: it must
    # observe the same state.
    r_prefs = await client.get("/api/v1/me/notification-prefs", headers=headers)
    assert r_prefs.status_code == 200
    assert r_prefs.json()["prefs"] == {"email": False, "whatsapp": True}

    # And GET /me/settings (fresh read) round-trips the same value.
    r_get = await client.get("/api/v1/me/settings", headers=headers)
    assert r_get.status_code == 200
    assert r_get.json()["data"]["notification_preferences"] == {
        "email": False,
        "whatsapp": True,
    }


async def test_settings_totp_enabled_reflects_totp_verify(
    client: AsyncClient,
) -> None:
    email = make_email()
    tokens = await register_and_login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r_setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert r_setup.status_code == 200
    secret = r_setup.json()["data"]["secret"]
    code = pyotp.TOTP(secret).now()

    r_verify = await client.post(
        "/api/v1/auth/totp/verify", headers=headers, json={"code": code}
    )
    assert r_verify.status_code == 200
    assert r_verify.json()["data"]["enabled"] is True

    r_settings = await client.get("/api/v1/me/settings", headers=headers)
    assert r_settings.status_code == 200
    assert r_settings.json()["data"]["totp_enabled"] is True


async def test_patch_settings_requires_auth(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/v1/me/settings", json={"email": True}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_INVALID"


async def test_patch_settings_user_row_must_exist(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker,
) -> None:
    """A signed JWT whose user row is gone gets the 401 envelope, not a 500."""
    from app.core.auth.tokens import create_access_token

    ghost_id = uuid.uuid4()
    token = create_access_token(ghost_id)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/v1/me/settings", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_INVALID"
