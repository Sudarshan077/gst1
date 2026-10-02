"""Shared test seed + guard-app helpers (v4 GSTIN-first model).

Every suite that needs a real tenant on the live PG:5436 seeds through these
helpers so the seeding path is identical to production (service layer, not
raw INSERTs) and GSTINs are always mod-36 valid synthetic fixtures.
"""

# NOTE: deliberately NO `from __future__ import annotations` here. The probe
# routes build their dependency factories as closure locals inside guard_app();
# with postponed annotations FastAPI cannot resolve those names from the module
# namespace and silently turns the guarded parameter into a required *query*
# param ("query.access: Field required") instead of a Depends().
import random
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from app.core.access import require_gstin_access, require_gstin_write
from app.core.auth.tokens import verify_access_token
from app.core.gst_accounts.service import create_gst_account, update_gst_account
from app.db.models.core import AccessRole, FilingScheme, GstAccount
from app.db.models.gst import FilingPeriod, FilingStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import register_and_login
from tests.gstin_fixtures import make_gstin

SessionMaker = async_sessionmaker[Any]


def _mobile() -> str:
    return "9" + "".join(random.SystemRandom().choice("0123456789") for _ in range(9))


async def seed_account(
    client: AsyncClient,
    sessionmaker: SessionMaker,
    *,
    legal_name: str = "Test Enterprise",
    aato_minor: int | None = None,
    trade_name: str | None = None,
    state_code: str = "27",
) -> tuple[dict[str, Any], GstAccount]:
    """Register+login a fresh user, attach one GSTIN, return (tokens, account).

    The creator becomes ADMIN on the GSTIN (v4: no business/registration layer).
    """
    tokens = await register_and_login(client, _mobile())
    user_id = verify_access_token(tokens["access_token"])
    async with sessionmaker() as session:
        account = await create_gst_account(
            session,
            gstin=make_gstin(state_code=state_code),
            legal_name=legal_name,
            created_by=user_id,
            trade_name=trade_name,
            aato_minor=aato_minor,
        )
        return tokens, account


async def seed_gstin_for_user(
    sessionmaker: SessionMaker,
    user_id: uuid.UUID,
    *,
    legal_name: str = "Second GSTIN Co",
    state_code: str = "27",
    aato_minor: int | None = None,
) -> GstAccount:
    """Attach a second GSTIN for an already-registered user."""
    async with sessionmaker() as session:
        return await create_gst_account(
            session,
            gstin=make_gstin(state_code=state_code),
            legal_name=legal_name,
            created_by=user_id,
            aato_minor=aato_minor,
        )


async def seed_open_period(
    sessionmaker: SessionMaker, gstin: str, fp: str
) -> None:
    """Create an OPEN filing period so uploads/review/confirm can run."""
    async with sessionmaker() as session:
        session.add(
            FilingPeriod(
                gstin=gstin,
                fp=fp,
                scheme_snapshot=FilingScheme.REGULAR_MONTHLY.value,
                status=FilingStatus.OPEN,
            )
        )
        await session.commit()


async def set_aato(
    sessionmaker: SessionMaker, gstin: str, aato_minor: int, role: AccessRole
) -> dict[str, Any]:
    """Re-run the PATCH service path so IRN threshold flags stay live."""
    async with sessionmaker() as session:
        return await update_gst_account(session, gstin, role, aato_minor=aato_minor)


def guard_app(sessionmaker: SessionMaker) -> Any:
    """create_app() with the session overridden + probe routes on the real guard.

    The probe routes wire the dependency factories exactly as the production
    routers do (no ad-hoc checks), so the matrix exercises the shipped guard.
    """
    from app.db.session import get_session
    from app.main import create_app
    from fastapi import APIRouter, Depends

    app = create_app()

    async def _override_session() -> AsyncGenerator[Any, None]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    router = APIRouter(prefix="/api/v1/probe", tags=["probe"])

    gstin_guard = require_gstin_access("gstin")
    gstin_write_guard = require_gstin_write("gstin")

    @router.get("/gstin/{gstin}")
    async def gstin_probe(access: Annotated[Any, Depends(gstin_guard)]) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "gstin": access.gstin,
                "role": access.role.value,
                "legal_name": access.legal_name,
            },
        }

    @router.get("/gstin/{gstin}/write-probe")
    async def write_probe(
        access: Annotated[Any, Depends(gstin_write_guard)],
    ) -> dict[str, object]:
        """Route guarded by require_gstin_write: VIEWER gets 403, FILER/ADMIN 200."""
        return {"success": True, "data": {"wrote": access.gstin, "role": access.role.value}}

    app.include_router(router)
    return app
