"""L2 auth suite — TOTP setup/verify + step-up token flow (API_SPEC §1).

TOTP is optional for every user. Here we prove the setup/verify lifecycle and
step-up token contract.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pyotp
import pytest
from app.core.auth import tokens as token_svc
from app.core.auth import totp as totp_svc
from app.core.auth.errors import TotpAlreadyEnabled, TotpInvalid
from app.db.models.core import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import _register_and_login, make_email

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


async def _login(client: AsyncClient) -> tuple[dict[str, Any], uuid.UUID]:
    """Register+login a FRESH user per call; returns (tokens, user_id)."""
    data = await _register_and_login(client, make_email())
    user_id = token_svc.verify_access_token(data["access_token"])
    return data, user_id


async def test_totp_setup_returns_secret_and_qr_uri(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    data, user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    resp = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["secret"]
    assert body["qr_uri"].startswith("otpauth://totp/")
    # secret persisted on the user row
    async with api_sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None and user.totp_secret == body["secret"]
        assert user.totp_enabled_at is None  # NOT enabled until verify


async def test_totp_verify_wrong_code_rejected_then_correct_enables(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    data, user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    secret = setup.json()["data"]["secret"]

    bad = await client.post("/api/v1/auth/totp/verify", headers=headers, json={"code": "000000"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "TOTP_INVALID"

    code = pyotp.TOTP(secret).now()
    good = await client.post("/api/v1/auth/totp/verify", headers=headers, json={"code": code})
    assert good.status_code == 200
    assert good.json()["data"]["enabled"] is True

    async with api_sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None and user.totp_enabled_at is not None


async def test_totp_setup_twice_conflicts_after_enable(client: AsyncClient) -> None:
    data, _user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    secret = setup.json()["data"]["secret"]
    code = pyotp.TOTP(secret).now()
    await client.post("/api/v1/auth/totp/verify", headers=headers, json={"code": code})
    again = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TOTP_ALREADY_ENABLED"


async def test_totp_unit_enable_requires_valid_code() -> None:
    secret = totp_svc.generate_secret()
    with pytest.raises(TotpInvalid):
        await totp_svc.enable_totp(secret, "000000")
    assert await totp_svc.enable_totp(secret, pyotp.TOTP(secret).now()) is True


async def test_totp_already_enabled_guard_unit() -> None:
    secret = totp_svc.generate_secret()
    with pytest.raises(TotpAlreadyEnabled):
        totp_svc.assert_not_enabled(secret, object())


async def test_totp_window_tolerance_unit() -> None:
    """valid_window=1 accepts the previous 30s step (clock drift)."""
    secret = totp_svc.generate_secret()
    t0 = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=30)
    prev_code = pyotp.TOTP(secret).at(t0)
    assert totp_svc.verify_code(secret, prev_code, valid_window=1) is True


async def test_totp_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/totp/setup")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] in {"TOKEN_INVALID", "MISSING_CREDENTIALS"}


async def test_me_reports_totp_enabled_flag(client: AsyncClient) -> None:
    data, _user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    secret = setup.json()["data"]["secret"]
    await client.post(
        "/api/v1/auth/totp/verify",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["data"]["user"]["totp_enabled"] is True


async def test_stepup_issues_verifiable_token(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """POST /auth/stepup with a fresh OTP -> stepup_token verifiable as JWT."""
    data, user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    async with api_sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        identifier = user.email

    req = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": identifier, "purpose": "LOGIN"}
    )
    otp = req.json()["data"]["dev_otp"]
    resp = await client.post("/api/v1/auth/stepup", headers=headers, json={"otp": otp})
    assert resp.status_code == 200, resp.text
    stepup_token = resp.json()["data"]["stepup_token"]
    assert token_svc.verify_stepup_token(stepup_token) == user_id


async def test_stepup_rejects_wrong_otp(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    data, user_id = await _login(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    async with api_sessionmaker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        await client.post(
            "/api/v1/auth/otp/request",
            json={"identifier": user.email, "purpose": "LOGIN"},
        )
    resp = await client.post("/api/v1/auth/stepup", headers=headers, json={"otp": "999999"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "OTP_INVALID"


async def test_totp_helper_generates_unique_secrets() -> None:
    secrets = {totp_svc.generate_secret() for _ in range(20)}
    assert len(secrets) == 20
