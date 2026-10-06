"""GST account service: create/read/update + collaborator grants (task 0.6).

v4.0 (TECHNICAL_ARCHITECTURE §3): the primary entity is the GSTIN. A user
attaches a GSTIN — creating it makes them its ADMIN — and every filing object
hangs off `core.gst_accounts.gstin` directly. There is no business/registration
surrogate id, and PAN is derived from GSTIN positions 3-12 rather than entered.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ServiceError
from app.core.access import audit
from app.core.gstin import validate_gstin
from app.db.models.core import (
    AccessRole,
    AuditLog,
    FilingScheme,
    GstAccount,
    User,
    UserGstAccess,
)

IRT_APPLICABLE_MINOR = 5_000_000_000  # ₹5 crore AATO threshold


class GstinNotFound(ServiceError):
    """404 — unknown GSTIN or no grant (existence must not leak)."""

    def __init__(self, message: str = "no access to this GSTIN") -> None:
        super().__init__(message, 404, "GSTIN_NOT_FOUND")


class GstinConflict(ServiceError):
    """409 — GSTIN already attached on the platform."""

    def __init__(self, message: str = "GSTIN already exists") -> None:
        super().__init__(message, 409, "CONFLICT")


class CollaboratorNotFound(ServiceError):
    def __init__(self, message: str = "collaborator not found") -> None:
        super().__init__(message, 404, "NOT_FOUND")


def _validate_and_extract(gstin: str) -> tuple[str, str, str]:
    """Return (gstin, pan, state_code) after mod-36 + regex validation."""
    try:
        clean = validate_gstin(gstin)
    except ValueError as exc:
        raise ServiceError(str(exc), 422, "VALIDATION_ERROR") from exc
    return clean, clean[2:12], clean[:2]


def _irn_applicable(aato_minor: int | None) -> bool:
    """IRN (e-invoicing) threshold: strictly above ₹5 crore AATO."""
    return bool(aato_minor is not None and aato_minor > IRT_APPLICABLE_MINOR)


async def create_gst_account(
    session: AsyncSession,
    *,
    gstin: str,
    legal_name: str,
    created_by: uuid.UUID,
    trade_name: str | None = None,
    registered_address: str | None = None,
    aato_minor: int | None = None,
    filing_scheme: FilingScheme = FilingScheme.REGULAR_MONTHLY,
) -> GstAccount:
    """Attach a GSTIN for `created_by`; the creator becomes its ADMIN."""
    clean, pan, state_code = _validate_and_extract(gstin)

    existing = await session.get(GstAccount, clean)
    if existing is not None:
        raise GstinConflict(f"GSTIN {clean} is already attached to an account")

    account = GstAccount(
        gstin=clean,
        pan=pan,
        legal_name=legal_name,
        trade_name=trade_name,
        state_code=state_code,
        filing_scheme=filing_scheme,
        irn_applicable=_irn_applicable(aato_minor),
        aato_latest_minor=aato_minor or 0,
        registered_address=registered_address,
    )
    session.add(account)
    session.add(
        UserGstAccess(user_id=created_by, gstin=clean, role=AccessRole.ADMIN)
    )
    try:
        await session.flush()
        await audit(
            session,
            action="GSTIN_ATTACHED",
            entity="gst_account",
            entity_id=clean,
            actor_user_id=created_by,
            gstin=clean,
            payload_diff={"after": {"role": "ADMIN"}},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise GstinConflict() from exc

    await session.refresh(account)
    return account


async def list_my_gst_accounts(
    session: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """GET /gst-accounts — every GSTIN the user can operate on, with role."""
    rows = (
        await session.execute(
            select(GstAccount, UserGstAccess.role)
            .join(UserGstAccess, UserGstAccess.gstin == GstAccount.gstin)
            .where(UserGstAccess.user_id == user_id)
            .order_by(GstAccount.created_at.asc())
        )
    ).all()
    return [_account_out(account, role) for account, role in rows]


async def get_gst_account(session: AsyncSession, gstin: str) -> GstAccount:
    """Fetch a GSTIN row or raise 404 (no existence leak)."""
    account = await session.get(GstAccount, gstin.strip().upper())
    if account is None:
        raise GstinNotFound()
    return account


async def get_gst_account_detail(
    session: AsyncSession, gstin: str, role: AccessRole
) -> dict[str, Any]:
    account = await get_gst_account(session, gstin)
    detail = _account_out(account, role)
    detail["collaborators"] = await list_collaborators(session, account.gstin)
    return detail


async def update_gst_account(
    session: AsyncSession,
    gstin: str,
    role: AccessRole,
    *,
    trade_name: str | None = None,
    registered_address: str | None = None,
    aato_minor: int | None = None,
    filing_scheme: FilingScheme | None = None,
) -> dict[str, Any]:
    """PATCH /gst-accounts/{gstin} — partial update; keeps IRN threshold live."""
    account = await get_gst_account(session, gstin)
    before = {
        "trade_name": account.trade_name,
        "aato_latest_minor": account.aato_latest_minor,
        "filing_scheme": account.filing_scheme.value,
    }

    if trade_name is not None:
        account.trade_name = trade_name
    if registered_address is not None:
        account.registered_address = registered_address
    if aato_minor is not None:
        account.aato_latest_minor = aato_minor
        account.irn_applicable = _irn_applicable(aato_minor)
    if filing_scheme is not None:
        account.filing_scheme = filing_scheme

    await audit(
        session,
        action="GSTIN_UPDATED",
        entity="gst_account",
        entity_id=account.gstin,
        actor_user_id=None,
        gstin=account.gstin,
        payload_diff={
            "before": before,
            "after": {
                "trade_name": account.trade_name,
                "aato_latest_minor": account.aato_latest_minor,
                "filing_scheme": account.filing_scheme.value,
            },
        },
    )
    await session.commit()
    await session.refresh(account)
    return _account_out(account, role)


# ------------------------------------------------------------- collaborators


async def add_collaborator(
    session: AsyncSession,
    gstin: str,
    *,
    email: str,
    role: AccessRole,
    actor_user_id: uuid.UUID,
) -> dict[str, Any]:
    """POST /gst-accounts/{gstin}/collaborators — grant an existing user access."""
    account = await get_gst_account(session, gstin)
    user = (
        await session.execute(select(User).where(User.email == email.strip().lower()))
    ).scalar_one_or_none()
    if user is None:
        raise CollaboratorNotFound(f"no user with email {email}")

    if user.id == actor_user_id:
        raise ServiceError("cannot re-invite yourself", 409, "CONFLICT")

    session.add(UserGstAccess(user_id=user.id, gstin=account.gstin, role=role))
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ServiceError("user already has access to this GSTIN", 409, "CONFLICT") from exc

    await audit(
        session,
        action="GSTIN_ACCESS_GRANTED",
        entity="user_gst_access",
        entity_id=str(user.id),
        actor_user_id=actor_user_id,
        gstin=account.gstin,
        payload_diff={"target_user": str(user.id), "role": role.value},
    )
    await session.commit()
    return {"user_id": str(user.id), "gstin": account.gstin, "role": role.value}


async def list_collaborators(session: AsyncSession, gstin: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(User, UserGstAccess.role)
            .join(UserGstAccess, UserGstAccess.user_id == User.id)
            .where(UserGstAccess.gstin == gstin.strip().upper())
            .order_by(UserGstAccess.granted_at.asc())
        )
    ).all()
    return [
        {
            "user_id": str(user.id),
            "email": user.email,
            "mobile": user.mobile,
            "full_name": user.full_name,
            "role": role.value,
            "granted_at": _iso(getattr(user, "created_at", None)),
        }
        for user, role in rows
    ]


async def revoke_collaborator(
    session: AsyncSession,
    gstin: str,
    *,
    target_user_id: uuid.UUID,
    role: AccessRole,
    actor_user_id: uuid.UUID,
) -> dict[str, Any]:
    """DELETE /gst-accounts/{gstin}/collaborators/{userId} — instant access death."""
    account = await get_gst_account(session, gstin)
    if role is not AccessRole.ADMIN:
        raise ServiceError("ADMIN role required on this GSTIN", 403, "FORBIDDEN")

    grant = (
        await session.execute(
            select(UserGstAccess).where(
                UserGstAccess.gstin == account.gstin,
                UserGstAccess.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise CollaboratorNotFound()
    if grant.role is AccessRole.ADMIN and await _admin_count(session, account.gstin) <= 1:
        raise ServiceError(
            "cannot revoke the last ADMIN of a GSTIN", 409, "CONFLICT"
        )

    await session.delete(grant)
    await audit(
        session,
        action="GSTIN_ACCESS_REVOKED",
        entity="user_gst_access",
        entity_id=str(target_user_id),
        actor_user_id=actor_user_id,
        gstin=account.gstin,
        payload_diff={"target_user": str(target_user_id), "role": grant.role.value},
    )
    await session.commit()
    return {"user_id": str(target_user_id), "gstin": account.gstin, "revoked": True}


async def update_collaborator(
    session: AsyncSession,
    gstin: str,
    target_user_id: uuid.UUID,
    new_role: AccessRole,
    actor_user_id: uuid.UUID,
) -> dict[str, Any]:
    """PATCH /gst-accounts/{gstin}/collaborators/{userId} — update role."""
    account = await get_gst_account(session, gstin)

    grant = (
        await session.execute(
            select(UserGstAccess).where(
                UserGstAccess.gstin == account.gstin,
                UserGstAccess.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise CollaboratorNotFound()

    old_role = grant.role
    grant.role = new_role

    await audit(
        session,
        action="GSTIN_ACCESS_UPDATED",
        entity="user_gst_access",
        entity_id=str(target_user_id),
        actor_user_id=actor_user_id,
        gstin=account.gstin,
        payload_diff={"old_role": old_role.value, "new_role": new_role.value},
    )
    await session.commit()
    return {"user_id": str(target_user_id), "gstin": account.gstin, "role": new_role.value}


async def _admin_count(session: AsyncSession, gstin: str) -> int:
    from sqlalchemy import func

    return (
        await session.execute(
            select(func.count())
            .select_from(UserGstAccess)
            .where(
                UserGstAccess.gstin == gstin,
                UserGstAccess.role == AccessRole.ADMIN,
            )
        )
    ).scalar_one()


async def recent_audit_rows(
    session: AsyncSession, gstin: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Read-only audit trail for one GSTIN (append-only rows, newest first)."""
    rows = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.gstin == gstin.strip().upper())
            .order_by(AuditLog.at.desc())
            .limit(limit)
        )
    ).scalars()
    return [_audit_out(row) for row in rows]


def _account_out(account: GstAccount, role: AccessRole) -> dict[str, Any]:
    return {
        "gstin": account.gstin,
        "legal_name": account.legal_name,
        "trade_name": account.trade_name,
        "pan": account.pan,
        "state_code": account.state_code,
        "filing_scheme": account.filing_scheme.value,
        "irn_applicable": account.irn_applicable,
        "aato_latest_minor": account.aato_latest_minor,
        "registered_address": account.registered_address,
        "role": role.value,
        "created_at": _iso(account.created_at),
    }


def _audit_out(row: AuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action": row.action,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "gstin": row.gstin,
        "payload_diff": row.payload_diff,
        "at": _iso(row.at),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
