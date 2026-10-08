"""Tests for POST /auth/logout-all — sign-out-everywhere (PHASE8 8.7).

Every refresh family the user owns is revoked (all devices); other users'
families are untouched; /me/settings sees the count drop to zero; the audit
row records SESSIONS_REVOKED_ALL.
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest
from app.core.auth import tokens as token_svc
from app.core.auth.tokens import REFRESH_TTL_SECONDS
from httpx import AsyncClient
from sqlalchemy import select

from tests.auth_helpers import SessionMaker, make_email, register_and_login

pytestmark = pytest.mark.asyncio


async def test_logout_all_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/logout-all")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_INVALID"


async def test_logout_all_revokes_every_family(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    api_sessionmaker: SessionMaker,
) -> None:
    """Two login devices -> logout-all -> both refresh tokens dead, count=2."""
    email = make_email()
    tokens1 = await register_and_login(client, email)
    tokens2 = await register_and_login(client, email)
    headers = {"Authorization": f"Bearer {tokens1['access_token']}"}

    # Pre: settings aggregate sees both families.
    r_settings = await client.get("/api/v1/me/settings", headers=headers)
    assert r_settings.status_code == 200
    assert r_settings.json()["data"]["session"]["active_sessions"] == 2

    r = await client.post("/api/v1/auth/logout-all", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["revoked_sessions"] == 2
    assert data["active_sessions"] == 0

    # Every rtk: token of the user is gone; both refresh tokens now 401.
    for tokens in (tokens1, tokens2):
        assert not await fake_redis.exists(f"rtk:{tokens['refresh_token']}")
        r_refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert r_refresh.status_code == 401

    # /me/settings reflects the zeroed session count.
    r_settings2 = await client.get("/api/v1/me/settings", headers=headers)
    assert r_settings2.status_code == 200
    assert r_settings2.json()["data"]["session"]["active_sessions"] == 0


async def test_logout_all_is_idempotent_and_scoped_to_user(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Second call revokes 0; another user's family survives untouched."""
    a = await register_and_login(client, make_email())
    b = await register_and_login(client, make_email())

    r1 = await client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["revoked_sessions"] == 1

    # Idempotent: nothing left to revoke.
    r2 = await client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["revoked_sessions"] == 0

    # User B was untouched.
    assert await fake_redis.exists(f"rtk:{b['refresh_token']}")
    r_b = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": b["refresh_token"]}
    )
    assert r_b.status_code == 200


async def test_revoke_all_families_spares_foreign_families(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Unit: only the caller's families die; TTL layout unchanged for others."""
    user = uuid.uuid4()
    other = uuid.uuid4()
    mine = await token_svc.issue_refresh_family(fake_redis, user)
    theirs = await token_svc.issue_refresh_family(fake_redis, other)

    revoked = await token_svc.revoke_all_families(fake_redis, user)
    assert revoked == 1
    assert not await fake_redis.exists(f"rtk:{mine}")
    assert await fake_redis.exists(f"rtk:{theirs}")
    ttl = await fake_redis.ttl(f"rtk:{theirs}")
    assert 7 * 24 * 3600 <= ttl <= REFRESH_TTL_SECONDS + 120


async def test_logout_all_writes_audit_row(
    client: AsyncClient,
    api_sessionmaker: SessionMaker,
) -> None:
    from app.core.auth.tokens import verify_access_token
    from app.db.models.core import AuditLog

    tokens = await register_and_login(client, make_email())
    user_id = verify_access_token(tokens["access_token"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = await client.post("/api/v1/auth/logout-all", headers=headers)
    assert r.status_code == 200

    async with api_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.actor_user_id == user_id,
                        AuditLog.action == "SESSIONS_REVOKED_ALL",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].payload_diff == {"revoked_sessions": 1}
