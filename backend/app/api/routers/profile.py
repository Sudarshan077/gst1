"""User profile router — GET/PATCH /me/profile (PHASE8_PRODUCT_COMPLETENESS 8.1).

`email` is read-only: the PATCH body model is extra="forbid" with only
`full_name`, so a patch carrying `{email}` is a 422 at the validation layer —
never a silent ignore. Both routes are user-scoped (require_user); there is no
GSTIN scope and no password/mobile surface.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ProfileEnvelope, ProfilePatchIn
from app.core.auth import service
from app.core.auth.dependencies import require_user
from app.db.session import get_session

router = APIRouter(prefix="/me", tags=["profile"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]


@router.get("/profile", response_model=ProfileEnvelope)
async def get_profile(session: SessionDep, user_id: UserDep) -> dict[str, object]:
    """GET /me/profile — own profile, same user shape as /auth/me."""
    return {"success": True, "data": await service.get_profile(session, user_id)}


@router.patch("/profile", response_model=ProfileEnvelope)
async def patch_profile(
    body: ProfilePatchIn, session: SessionDep, user_id: UserDep
) -> dict[str, object]:
    """PATCH /me/profile — edit own full_name only; audit PROFILE_UPDATED."""
    return {"success": True, "data": await service.update_profile(session, user_id, body.full_name)}
