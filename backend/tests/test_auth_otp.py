"""L2 auth suite — OTP request/verify + rate limit + expiry/attempts.

Covers SECURITY_AND_ACCESS.md §1/§7 and the task 0.4 done_when "incl. rate
limit". Redis = fakeredis (fresh per test); PG = live :5436; every test gets a
unique email so the shared dev DB never couples tests.
"""

from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
from app.config import get_settings
from app.core.auth import otp as otp_svc
from app.core.auth.errors import OtpExpired, OtpRateLimited
from httpx import AsyncClient

from tests.auth_helpers import _register_and_login

pytestmark = pytest.mark.asyncio


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@test.example"


async def test_otp_request_returns_dev_otp_in_dev_mode(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": _email(), "purpose": "LOGIN"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["otp_sent"] is True
    assert body["data"]["dev_otp"] is not None
    assert len(body["data"]["dev_otp"]) == get_settings().otp_length


async def test_otp_request_rejects_mobile_identifier(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/otp/request",
        json={"identifier": "9876543210", "purpose": "LOGIN"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IDENTIFIER_INVALID"


async def test_otp_verify_new_user_auto_created_on_register(client: AsyncClient) -> None:
    email = _email()
    data = await _register_and_login(client, email)
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == email.lower()
    # /auth/me works with the fresh access token
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["data"]["user"]["email"] == email.lower()


async def test_otp_verify_login_purpose_rejects_unknown_user(client: AsyncClient) -> None:
    email = _email()  # never registered
    resp = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "LOGIN"}
    )
    otp = resp.json()["data"]["dev_otp"]
    ver = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": otp}
    )
    assert ver.status_code == 401
    assert ver.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_otp_verify_wrong_code_fails_and_counts_attempts(
    client: AsyncClient, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "REGISTER"}
    )
    resp = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": "000000"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "OTP_INVALID"
    # attempt counter persisted in Redis
    raw = await fake_redis.get(f"otp:{email.lower()}")
    assert raw is not None and isinstance(raw, str)
    record = json.loads(raw)
    assert record["attempts"] == 1


async def test_otp_verify_exhausts_attempts_then_kills_otp(
    client: AsyncClient, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "LOGIN"}
    )
    max_attempts = get_settings().otp_max_verify_attempts
    last = None
    for _ in range(max_attempts):
        last = await client.post(
            "/api/v1/auth/otp/verify", json={"identifier": email, "otp": "000000"}
        )
    assert last is not None and last.status_code == 429
    assert last.json()["error"]["code"] == "OTP_TOO_MANY_ATTEMPTS"
    # even the CORRECT code no longer works — the OTP is dead
    assert await fake_redis.get(f"otp:{email.lower()}") is None


async def test_otp_unit_expiry_and_single_use(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Unit-level: verify_otp raises OtpExpired when nothing stored; single-use."""
    email = _email()
    await otp_svc.request_otp(fake_redis, email, "LOGIN")
    code_record = await fake_redis.get(f"otp:{email.lower()}")
    assert code_record is not None and isinstance(code_record, str)
    code = json.loads(code_record)["code"]
    purpose = await otp_svc.verify_otp(fake_redis, email, code)
    assert purpose == "LOGIN"
    with pytest.raises(OtpExpired):
        await otp_svc.verify_otp(fake_redis, email, code)  # replay = expired


async def test_otp_rate_limit_5_per_hour_per_identifier(
    client: AsyncClient,
) -> None:
    """THE done_when rate-limit test: 5 requests ok, 6th is 429; other ids unaffected."""
    email = _email()
    other = _email()
    limit = get_settings().otp_request_limit_per_hour
    statuses = []
    for _ in range(limit + 1):
        resp = await client.post(
            "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "LOGIN"}
        )
        statuses.append((resp.status_code, resp.json().get("error", {}).get("code")))
    assert statuses[:limit] == [(200, None)] * limit
    assert statuses[limit] == (429, "OTP_RATE_LIMITED")
    # an unrelated identifier still gets OTPs (per-identifier, not global)
    other_resp = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": other, "purpose": "LOGIN"}
    )
    assert other_resp.status_code == 200


async def test_otp_rate_limit_unit_direct(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Service-level mirror: OtpRateLimited raised past the 5th request."""
    email = _email()
    for _ in range(5):
        await otp_svc.request_otp(fake_redis, email, "LOGIN")
    with pytest.raises(OtpRateLimited):
        await otp_svc.request_otp(fake_redis, email, "LOGIN")


async def test_otp_invalid_identifier_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": "not-an-id", "purpose": "LOGIN"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IDENTIFIER_INVALID"


async def test_otp_wrong_code_then_correct_code_still_works(client: AsyncClient) -> None:
    """Correct code works after failed attempts (attempts < max)."""
    email = _email()
    req = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "REGISTER"}
    )
    dev_otp = req.json()["data"]["dev_otp"]
    await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": "111111"}
    )
    ver = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": dev_otp}
    )
    assert ver.status_code == 200
    assert ver.json()["data"]["access_token"]


async def test_otp_verify_is_single_use_across_logins(client: AsyncClient) -> None:
    """The same verified code cannot log in twice (OTP deleted on success)."""
    email = _email()
    req = await client.post(
        "/api/v1/auth/otp/request", json={"identifier": email, "purpose": "REGISTER"}
    )
    dev_otp = req.json()["data"]["dev_otp"]
    first = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": dev_otp}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/otp/verify", json={"identifier": email, "otp": dev_otp}
    )
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "OTP_EXPIRED"

