"""Auth me/stepup integration tests (task 0.7A, v4 unified profile)."""

from __future__ import annotations

import json as _json
import uuid
from typing import Any

import fakeredis.aioredis
import pyotp
import pytest
from app.core.auth import tokens as token_svc
from app.core.auth.dependencies import require_stepup
from app.core.auth.errors import StepUpRequired, TokenInvalid
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import _register_and_login, make_email

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


async def _register_totp(
    client: AsyncClient,
) -> tuple[dict[str, Any], uuid.UUID]:
    """Register -> TOTP setup + verify.

    Returns (token_data, user_id).
    """
    data = await _register_and_login(client, make_email())
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["data"]["secret"]

    code = pyotp.TOTP(secret).now()
    verify = await client.post(
        "/api/v1/auth/totp/verify",
        headers=headers,
        json={"code": code},
    )
    assert verify.status_code == 200, verify.text

    user_id = token_svc.verify_access_token(data["access_token"])
    return data, user_id


async def test_me_v4_unified_profile(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """v4: REGISTER -> TOTP -> GET /auth/me = 200, returns user + gstins list."""
    data, _user_id = await _register_totp(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["success"] is True
    assert "gst_accounts" in body["data"]
    assert isinstance(body["data"]["gst_accounts"], list)
    assert body["data"]["user"]["totp_enabled"] is True


async def test_require_stepup_contract(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """4(c): no header -> 403 STEP_UP_REQUIRED; own stepup -> ok; other -> 401."""
    data, user_id = await _register_totp(client)

    from starlette.requests import Request

    # no step-up header
    bare_request = Request({"type": "http", "headers": []})
    with pytest.raises(StepUpRequired) as step_exc_info:
        await require_stepup(bare_request, None, user_id)  # type: ignore[arg-type]
    assert step_exc_info.value.status_code == 403
    assert step_exc_info.value.code == "STEP_UP_REQUIRED"

    # valid own token
    own_token = token_svc.create_stepup_token(user_id)
    good_request = Request({
        "type": "http",
        "headers": [(b"x-stepup-token", own_token.encode())],
    })
    assert await require_stepup(good_request, None, user_id) == user_id  # type: ignore[arg-type]

    # another user's token
    other_id = uuid.uuid4()
    bad_token = token_svc.create_stepup_token(other_id)
    bad_request = Request({
        "type": "http",
        "headers": [(b"x-stepup-token", bad_token.encode())],
    })
    with pytest.raises(TokenInvalid) as token_exc_info:
        await require_stepup(bad_request, None, user_id)  # type: ignore[arg-type]
    assert token_exc_info.value.code == "TOKEN_INVALID"


async def test_totp_guard_on_protected_action(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """4(d): TOTP-less user profile reports totp_enabled == False."""
    data = await _register_and_login(client, make_email())
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["user"]["totp_enabled"] is False

    # TOTP setup + verify
    setup = await client.post("/api/v1/auth/totp/setup", headers=headers)
    secret = setup.json()["data"]["secret"]
    await client.post(
        "/api/v1/auth/totp/verify",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )

    me_after = await client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 200
    assert me_after.json()["data"]["user"]["totp_enabled"] is True


async def test_stepup_with_email_otp(
    client: AsyncClient, api_sessionmaker: SessionMaker, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """4(e): stepup with email OTP succeeds."""
    data, _user_id = await _register_totp(client)
    access = data["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    user_id = token_svc.verify_access_token(access)
    async with api_sessionmaker() as session:
        from app.db.models.core import User

        user = await session.get(User, user_id)
        assert user is not None
        email = user.email

    # Request OTP against the email identifier
    req = await client.post(
        "/api/v1/auth/otp/request",
        json={"identifier": email, "purpose": "LOGIN"},
    )
    assert req.status_code == 200, req.text
    otp = req.json()["data"]["dev_otp"]

    resp = await client.post(
        "/api/v1/auth/stepup",
        headers=headers,
        json={"otp": otp},
    )
    assert resp.status_code == 200, resp.text
    assert "stepup_token" in resp.json()["data"]


async def test_stepup_wrong_otp_increments_attempts(
    client: AsyncClient, api_sessionmaker: SessionMaker, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """4(f): wrong OTP with email live -> 401 OTP_INVALID and attempts increment."""
    data, _user_id = await _register_totp(client)
    access = data["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    user_id = token_svc.verify_access_token(access)
    async with api_sessionmaker() as session:
        from app.db.models.core import User

        user = await session.get(User, user_id)
        assert user is not None
        email = user.email

    req = await client.post(
        "/api/v1/auth/otp/request",
        json={"identifier": email, "purpose": "LOGIN"},
    )
    assert req.status_code == 200, req.text

    # First wrong attempt increments attempts to 1
    resp1 = await client.post(
        "/api/v1/auth/stepup",
        headers=headers,
        json={"otp": "000000"},
    )
    assert resp1.status_code == 401
    assert resp1.json()["error"]["code"] == "OTP_INVALID"

    raw = await fake_redis.get(f"otp:{email}")
    assert raw is not None, f"otp:{email} should still exist"
    rec = _json.loads(raw)
    assert rec["attempts"] == 1, f"otp:{email} attempts = {rec['attempts']}"


async def test_otp_too_many_attempts_kills_key_unit(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Direct-service proof: after max wrong attempts the OTP key is deleted."""
    from app.core.auth import otp as otp_svc
    from app.core.auth.errors import OtpInvalid, OtpTooManyAttempts

    email = make_email()
    await otp_svc.request_otp(fake_redis, email, "LOGIN")
    rec = await otp_svc.peek_otp(fake_redis, email)
    assert rec is not None
    code = str(rec["code"])

    # Build a pool of wrong codes; the exact value of code does not matter
    # because the service increments attempts before comparing.
    wrong_codes = [f"{i:06d}" for i in range(10) if f"{i:06d}" != code]
    max_attempts = 5
    for idx in range(max_attempts - 1):
        try:
            await otp_svc.verify_otp(fake_redis, email, wrong_codes[idx])
        except OtpInvalid:
            pass

    with pytest.raises(OtpTooManyAttempts):
        await otp_svc.verify_otp(fake_redis, email, wrong_codes[max_attempts - 1])
    assert not await fake_redis.exists(f"otp:{email}")
