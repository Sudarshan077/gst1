"""Auth service — orchestrates OTP/JWT/TOTP with the users table."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import audit
from app.core.auth import otp as otp_svc
from app.core.auth import tokens as token_svc
from app.core.auth import totp as totp_svc
from app.core.auth.errors import (
    InvalidCredentials,
    TokenInvalid,
    TotpInvalid,
)
from app.core.auth.hashing import verify_password
from app.core.auth.redis_client import get_redis
from app.db.models.core import GstAccount, User, UserGstAccess


def _user_out(user: User) -> dict[str, object]:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "totp_enabled": user.totp_enabled_at is not None,
    }


async def request_otp(session: AsyncSession, identifier: str, purpose: str) -> dict[str, object]:
    """POST /auth/otp/request — rate-limited OTP issuance (dev echoes dev_otp)."""
    redis = get_redis()
    result = await otp_svc.request_otp(redis, identifier, purpose)
    return {"otp_sent": result.otp_sent, "dev_otp": result.dev_otp}


async def verify_otp(
    session: AsyncSession, identifier: str, code: str
) -> tuple[dict[str, object], dict[str, str]]:
    """POST /auth/otp/verify — LOGIN or REGISTER.

    New users are auto-created on REGISTER; the login identifier is the email.
    """
    redis = get_redis()
    purpose = await otp_svc.verify_otp(redis, identifier, code)
    user = (
        await session.execute(
            select(User).where(User.email == identifier.strip().lower())
        )
    ).scalar_one_or_none()
    if user is None:
        if purpose == "REGISTER":
            email = identifier.strip().lower()
            full_name = f"User {email.split('@')[0][-4:]}"
            user = User(
                email=email,
                full_name=full_name,
            )
            session.add(user)
            await session.commit()
        else:
            raise InvalidCredentials("no account for this email — register first")

    access = token_svc.create_access_token(user.id)
    refresh = await token_svc.issue_refresh_family(redis, user.id)
    return _user_out(user), {"access_token": access, "refresh_token": refresh}


async def login_with_password(
    session: AsyncSession, identifier: str, password: str
) -> tuple[dict[str, object], dict[str, str]]:
    """POST /auth/login/password"""
    user = (
        await session.execute(
            select(User).where(User.email == identifier.strip().lower())
        )
    ).scalar_one_or_none()
    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        raise InvalidCredentials("invalid email or password")

    redis = get_redis()
    access = token_svc.create_access_token(user.id)
    refresh = await token_svc.issue_refresh_family(redis, user.id)
    return _user_out(user), {"access_token": access, "refresh_token": refresh}



async def refresh(session: AsyncSession, refresh_token: str) -> tuple[dict[str, str], str]:
    """POST /auth/refresh — rotate; reuse of a rotated token kills the family.

    Returns ((access_token, refresh_token), user_id) — the access JWT is fresh;
    the new refresh token MUST reach the client (httpOnly cookie at wiring).
    """
    redis = get_redis()
    new_refresh, user_id = await token_svc.rotate_refresh_token(redis, refresh_token)
    access = token_svc.create_access_token(user_id)
    return {"access_token": access, "refresh_token": new_refresh}, str(user_id)


async def stepup(session: AsyncSession, user_id: uuid.UUID, otp: str) -> dict[str, str]:
    """POST /auth/stepup — fresh OTP proves the user for sensitive routes.

    The OTP must have been requested for the user's email; verify consumes the
    code and returns a step-up token.
    """
    redis = get_redis()
    user = await session.get(User, user_id)
    if user is None:
        raise InvalidCredentials("unknown user")
    identifier = user.email
    if not identifier:
        raise InvalidCredentials("user has no email")
    await otp_svc.verify_otp(redis, identifier, otp)
    return {"stepup_token": token_svc.create_stepup_token(user_id)}


async def totp_setup(session: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    """POST /auth/totp/setup — mint + store a pending secret, return QR URI."""
    user = await session.get(User, user_id)
    if user is None:
        raise InvalidCredentials("unknown user")
    totp_svc.assert_not_enabled(user.totp_secret, user.totp_enabled_at)
    secret = totp_svc.generate_secret()
    user.totp_secret = secret
    await session.commit()
    return {
        "secret": secret,
        "qr_uri": totp_svc.provisioning_uri(secret, user.email),
    }


async def totp_verify(session: AsyncSession, user_id: uuid.UUID, code: str) -> dict[str, bool]:
    """POST /auth/totp/verify — client-side verify flips totp_enabled_at."""
    user = await session.get(User, user_id)
    if user is None:
        raise InvalidCredentials("unknown user")
    if user.totp_secret is None:
        raise TotpInvalid("no TOTP setup in progress — call /auth/totp/setup first")
    if not totp_svc.verify_code(user.totp_secret, code):
        raise TotpInvalid("invalid TOTP code")
    user.totp_enabled_at = dt.datetime.now(tz=dt.UTC)
    await session.commit()
    return {"enabled": True}



async def update_user_totp_secret(session: AsyncSession, user_id: uuid.UUID, secret: str) -> None:
    """Reset path (step-up protected at the route layer)."""
    await session.execute(update(User).where(User.id == user_id).values(totp_secret=secret))
    await session.commit()


async def me(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object]:
    """GET /auth/me — profile + every GSTIN the user can operate on, with role.

    v4.0 removed businesses/ca_firms; access resolves through user_gst_access
    (users.id -> gst_accounts.gstin). The v2 firm_id / businesses fields are gone
    from the response.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise TokenInvalid("user no longer exists")
    rows = (
        await session.execute(
            select(UserGstAccess.gstin, UserGstAccess.role, GstAccount.legal_name)
            .join(GstAccount, GstAccount.gstin == UserGstAccess.gstin)
            .where(UserGstAccess.user_id == user_id)
            .order_by(UserGstAccess.granted_at.asc())
        )
    ).all()
    return {
        "user": _user_out(user),
        "gst_accounts": [
            {"gstin": str(gstin), "role": role.value, "legal_name": legal_name}
            for gstin, role, legal_name in rows
        ],
    }


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object]:
    """GET /me/profile — the caller's own profile (PHASE8 8.1).

    Returns the same user shape as /auth/me's `data.user`.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise TokenInvalid("user no longer exists")
    return _user_out(user)


async def update_profile(
    session: AsyncSession, user_id: uuid.UUID, full_name: str
) -> dict[str, object]:
    """PATCH /me/profile — edit own full_name; email is read-only (PHASE8 8.1).

    The route's ProfilePatchIn (extra="forbid") already rejects an email patch
    as 422; this function only ever touches full_name. Writes one append-only
    audit row (PROFILE_UPDATED) in the same transaction as the edit.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise TokenInvalid("user no longer exists")

    old_name = user.full_name
    user.full_name = full_name.strip()
    await audit(
        session,
        action="PROFILE_UPDATED",
        entity="user",
        entity_id=str(user.id),
        actor_user_id=user_id,
        payload_diff={"full_name": {"old": old_name, "new": user.full_name}},
    )
    await session.commit()
    return _user_out(user)
