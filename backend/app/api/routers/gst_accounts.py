"""GST account router — API_SPECIFICATION.md §2 (task 0.6, v4 GSTIN-first).

Routes:
  POST   /gst-accounts
  GET    /gst-accounts
  GET    /gst-accounts/{gstin}
  PATCH  /gst-accounts/{gstin}
  GET    /gst-accounts/{gstin}/audit
  POST   /gst-accounts/{gstin}/collaborators
  GET    /gst-accounts/{gstin}/collaborators
  DELETE /gst-accounts/{gstin}/collaborators/{user_id}

Every GSTIN-scoped route goes through `require_gstin_access` (API_SPEC
non-negotiable #1) — the mutation routes additionally require FILER/ADMIN.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_gst import (
    CollaboratorInviteIn,
    GstAccountCreateIn,
    GstAccountPatchIn,
)
from app.core.access import GstinAccess, require_gstin_access, require_gstin_write
from app.core.auth.dependencies import require_user
from app.core.gst_accounts import service
from app.db.models.core import AccessRole, FilingScheme
from app.db.session import get_session

router = APIRouter(prefix="/gst-accounts", tags=["gst-accounts"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]
GstinDep = Annotated[GstinAccess, Depends(require_gstin_access("gstin"))]
GstinWriteDep = Annotated[GstinAccess, Depends(require_gstin_write("gstin"))]


@router.post("")
async def create_gst_account(
    body: GstAccountCreateIn,
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    scheme = (
        FilingScheme(body.filing_scheme)
        if body.filing_scheme
        else FilingScheme.REGULAR_MONTHLY
    )
    account = await service.create_gst_account(
        session,
        gstin=body.gstin,
        legal_name=body.legal_name,
        created_by=user_id,
        trade_name=body.trade_name,
        registered_address=body.registered_address,
        aato_minor=body.aato_minor,
        filing_scheme=scheme,
    )
    return {"success": True, "data": service._account_out(account, AccessRole.ADMIN)}


@router.get("")
async def list_gst_accounts(session: SessionDep, user_id: UserDep) -> dict[str, Any]:
    return {"success": True, "data": await service.list_my_gst_accounts(session, user_id)}


@router.get("/{gstin}")
async def get_gst_account(
    access: GstinDep,
    session: SessionDep,
) -> dict[str, Any]:
    detail = await service.get_gst_account_detail(session, access.gstin, access.role)
    return {"success": True, "data": detail}


@router.patch("/{gstin}")
async def patch_gst_account(
    body: GstAccountPatchIn,
    access: GstinWriteDep,
    session: SessionDep,
) -> dict[str, Any]:
    scheme = FilingScheme(body.filing_scheme) if body.filing_scheme else None
    data = await service.update_gst_account(
        session,
        access.gstin,
        access.role,
        trade_name=body.trade_name,
        registered_address=body.registered_address,
        aato_minor=body.aato_minor,
        filing_scheme=scheme,
    )
    return {"success": True, "data": data}


@router.get("/{gstin}/audit")
async def get_gstin_audit(
    access: GstinDep,
    session: SessionDep,
) -> dict[str, Any]:
    rows = await service.recent_audit_rows(session, access.gstin)
    return {"success": True, "data": rows}


@router.post("/{gstin}/collaborators")
async def invite_collaborator(
    body: CollaboratorInviteIn,
    access: GstinWriteDep,
    session: SessionDep,
) -> dict[str, Any]:
    data = await service.add_collaborator(
        session,
        access.gstin,
        email=body.email,
        role=AccessRole(body.role),
        actor_user_id=access.user_id,
    )
    return {"success": True, "data": data}


@router.get("/{gstin}/collaborators")
async def list_collaborators(
    access: GstinDep,
    session: SessionDep,
) -> dict[str, Any]:
    return {
        "success": True,
        "data": await service.list_collaborators(session, access.gstin),
    }


@router.delete("/{gstin}/collaborators/{user_id}")
async def revoke_collaborator(
    user_id: uuid.UUID,
    access: GstinDep,
    session: SessionDep,
) -> dict[str, Any]:
    data = await service.revoke_collaborator(
        session,
        access.gstin,
        target_user_id=user_id,
        role=access.role,
        actor_user_id=access.user_id,
    )
    return {"success": True, "data": data}
