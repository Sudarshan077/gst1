"""L2 auth fixtures: fakeredis-backed app client + scratch user rows.

The API app runs fully in-process (httpx ASGITransport) against the live PG
(:5436) via the app's async session; Redis is faked (fakeredis) per test so
OTP/rate-limit/family state never leaks between tests.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.auth import redis_client as redis_client_mod
from app.db.models.core import User
from app.main import create_app

TEST_DB_URL = "postgresql+asyncpg://gst:gst_dev_pass@127.0.0.1:5436/gst_filing_db"
os.environ.setdefault("GST_DATABASE_ASYNC_URL", TEST_DB_URL)

SessionMaker = async_sessionmaker[Any]


@pytest.fixture()
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Fresh fakeredis per test; injected as the app's Redis client."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client_mod.set_client(client)
    return client


@pytest_asyncio.fixture()
async def api_sessionmaker() -> AsyncGenerator[SessionMaker, None]:
    engine = create_async_engine(TEST_DB_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(
    fake_redis: fakeredis.aioredis.FakeRedis,
    api_sessionmaker: SessionMaker,
) -> AsyncGenerator[AsyncClient, None]:
    """ASGI client wired to the real app + live PG + fakeredis."""
    from app.db.session import get_session

    app = create_app()

    async def _override_session() -> AsyncGenerator[Any, None]:
        async with api_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    redis_client_mod.set_client(None)


async def make_user(
    sessionmaker: SessionMaker, email: str | None = None
) -> User:
    """Seed a user row directly (no OTP round-trip needed for /me etc.)."""
    async with sessionmaker() as session:
        user = User(
            email=email or f"{uuid4hex()}@test.local",
            full_name="Test User",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def make_email() -> str:
    """Return a unique email string for OTP tests."""
    # Test-only random local part; not used for cryptographic material.
    return f"test_{uuid4hex()}@example.com"


async def register_and_login(client: AsyncClient, email: str) -> dict[str, Any]:
    """Full OTP journey: request (dev echo) -> verify -> token pair."""
    req = await client.post(
        "/api/v1/auth/otp/request",
        json={"identifier": email, "purpose": "REGISTER"},
    )
    assert req.status_code == 200, req.text
    dev_otp = req.json()["data"]["dev_otp"]
    assert dev_otp, "dev mode must echo dev_otp for tests"
    ver = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": dev_otp}
    )
    assert ver.status_code == 200, ver.text
    envelope: dict[str, Any] = ver.json()
    data: dict[str, Any] = envelope["data"]
    return data


# Back-compat aliases for test modules imported before the rename.
_register_and_login = register_and_login
_make_user = make_user

# Deprecated: mobile-based fixtures are no longer valid under the email-only
# auth model. Kept as a thin wrapper around make_email() so unrelated suites
# that still import the name continue to get a usable identifier.
make_mobile = make_email


def redis_view(fake_redis: fakeredis.aioredis.FakeRedis) -> Redis:
    """Typing shim: fakeredis client used through the async API."""
    return fake_redis


def uuid4hex() -> str:
    """9-character hex suffix for unique local parts."""
    import uuid

    return uuid.uuid4().hex[:9]
