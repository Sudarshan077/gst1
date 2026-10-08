"""Task 8.1 — GET/PATCH /me/profile (PHASE8_PRODUCT_COMPLETENESS §3.1).

Covers: profile read, patch full_name → 200 + persisted, patch carrying
{email} → 422 (email is read-only — never silently ignored), the audit row
(PROFILE_UPDATED) written on edit, and that /auth/me reflects the edit.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.auth.tokens import verify_access_token
from app.db.models.core import AuditLog
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_email, register_and_login

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


def _headers(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_get_profile_returns_user_shape(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """GET /me/profile = 200 with the same user shape as /auth/me's data.user."""
    data = await register_and_login(client, make_email())
    user_id = verify_access_token(data["access_token"])

    resp = await client.get("/api/v1/me/profile", headers=_headers(data))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    user = body["data"]
    assert user["id"] == str(user_id)
    assert user["email"] == data["user"]["email"]
    assert user["full_name"] == data["user"]["full_name"]
    assert user["totp_enabled"] is False
    # same field set as /auth/me's user dto
    assert set(user.keys()) == set(data["user"].keys())


async def test_patch_full_name_persists_and_audits(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """PATCH {full_name} → 200; persists in DB; one PROFILE_UPDATED audit row
    with actor + old/new diff; /auth/me reflects the new name."""
    data = await register_and_login(client, make_email())
    user_id = verify_access_token(data["access_token"])
    old_name = data["user"]["full_name"]
    new_name = "Anthony Gowda"

    resp = await client.patch(
        "/api/v1/me/profile", headers=_headers(data), json={"full_name": new_name}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["full_name"] == new_name

    # persisted in the DB, not just echoed
    async with api_sessionmaker() as session:
        row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "PROFILE_UPDATED",
                    AuditLog.actor_user_id == user_id,
                )
            )
        )
        audit_rows = row.scalars().all()
    assert len(audit_rows) == 1, f"expected 1 PROFILE_UPDATED row, got {len(audit_rows)}"
    log = audit_rows[0]
    assert log.entity == "user"
    assert log.entity_id == str(user_id)
    assert log.gstin is None  # user-scoped, not registration-scoped
    assert log.payload_diff == {"full_name": {"old": old_name, "new": new_name}}

    # /auth/me reflects the edit
    me = await client.get("/api/v1/auth/me", headers=_headers(data))
    assert me.status_code == 200, me.text
    assert me.json()["data"]["user"]["full_name"] == new_name

    # a read-back confirms the persisted value
    again = await client.get("/api/v1/me/profile", headers=_headers(data))
    assert again.status_code == 200
    assert again.json()["data"]["full_name"] == new_name


async def test_patch_email_is_rejected_422(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """PATCH {email} → 422 — email is read-only, never silently ignored;
    no audit row and no DB change result from the rejected request."""
    data = await register_and_login(client, make_email())
    user_id = verify_access_token(data["access_token"])
    original_email = data["user"]["email"]

    resp = await client.patch(
        "/api/v1/me/profile",
        headers=_headers(data),
        json={"email": "hacker@evil.example"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # no audit row was written by the rejected request
    async with api_sessionmaker() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.actor_user_id == user_id,
                    AuditLog.action == "PROFILE_UPDATED",
                )
            )
        )
        audit_rows = rows.scalars().all()
    assert audit_rows == []

    # email unchanged even when sent alongside a valid full_name
    resp2 = await client.patch(
        "/api/v1/me/profile",
        headers=_headers(data),
        json={"full_name": "Legit Name", "email": "hacker@evil.example"},
    )
    assert resp2.status_code == 422, resp2.text

    profile = await client.get("/api/v1/me/profile", headers=_headers(data))
    assert profile.status_code == 200
    assert profile.json()["data"]["email"] == original_email


async def test_profile_requires_auth(client: AsyncClient) -> None:
    """No bearer token → 401 on both routes (guard contract)."""
    get_resp = await client.get("/api/v1/me/profile")
    assert get_resp.status_code == 401

    patch_resp = await client.patch(
        "/api/v1/me/profile", json={"full_name": "No Auth"}
    )
    assert patch_resp.status_code == 401


async def test_patch_rejects_empty_full_name(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """PATCH {full_name: ""} → 422 (min_length=1)."""
    data = await register_and_login(client, make_email())
    resp = await client.patch(
        "/api/v1/me/profile", headers=_headers(data), json={"full_name": ""}
    )
    assert resp.status_code == 422, resp.text


async def test_patch_does_not_touch_other_users(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """User A's PATCH never changes user B — the actor is the bearer identity."""
    a = await register_and_login(client, make_email())
    b = await register_and_login(client, make_email())
    b_email = b["user"]["email"]
    b_id = verify_access_token(b["access_token"])

    resp = await client.patch(
        "/api/v1/me/profile", headers=_headers(a), json={"full_name": "User A Only"}
    )
    assert resp.status_code == 200, resp.text

    b_profile = await client.get("/api/v1/me/profile", headers=_headers(b))
    assert b_profile.status_code == 200
    assert b_profile.json()["data"]["id"] == str(b_id)
    assert b_profile.json()["data"]["email"] == b_email
    assert b_profile.json()["data"]["full_name"] == b["user"]["full_name"]
