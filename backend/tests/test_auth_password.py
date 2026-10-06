from __future__ import annotations

import uuid

import pytest
from app.core.auth.hashing import get_password_hash
from app.db.models.core import User
from httpx import AsyncClient

from tests.auth_helpers import SessionMaker

pytestmark = pytest.mark.asyncio


async def test_password_login_success(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    # 1. Setup user with password
    email = f"test_{uuid.uuid4().hex[:6]}@example.com"
    password = "secure_password"
    async with api_sessionmaker() as session:
        user = User(
            email=email,
            full_name="Test User",
            password_hash=get_password_hash(password),
        )
        session.add(user)
        await session.commit()

    # 2. Test login
    resp = await client.post(
        "/api/v1/auth/login/password", json={"identifier": email, "password": password}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert data["data"]["user"]["email"] == email


async def test_password_login_failure(client: AsyncClient, api_sessionmaker: SessionMaker) -> None:
    # 1. Setup user with password
    email = f"test2_{uuid.uuid4().hex[:6]}@example.com"
    password = "secure_password"
    async with api_sessionmaker() as session:
        user = User(
            email=email,
            full_name="Test User 2",
            password_hash=get_password_hash(password),
        )
        session.add(user)
        await session.commit()

    # 2. Test wrong password
    resp = await client.post(
        "/api/v1/auth/login/password", json={"identifier": email, "password": "wrong_password"}
    )
    assert resp.status_code == 401

    # 3. Test non-existent user
    resp = await client.post(
        "/api/v1/auth/login/password",
        json={"identifier": "nonexistent@example.com", "password": password},
    )
    assert resp.status_code == 401
