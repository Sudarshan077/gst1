import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_gst import Gstr2bImportIn, Gstr2bStatementOut, ItcReconciliationOut
from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_user
from app.db.session import get_session
from app.services.returns.gsp_adapter import fetch_gstr2b_gsp
from app.services.returns.gstr2b import import_gstr2b, reconcile_itc

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

router = APIRouter(prefix="/gst-accounts/{gstin}/months/{fp}", tags=["itc"])

@router.post("/gstr2b/import")
async def import_2b_statement(
    gstin: str,
    fp: str,
    body: Gstr2bImportIn,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    statement = await import_gstr2b(session, gstin, fp, body.payload, user_id)
    return {"success": True, "data": Gstr2bStatementOut.model_validate(statement)}


@router.post("/gstr2b/fetch")
async def fetch_2b_via_gsp(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    statement = await fetch_gstr2b_gsp(session, gstin, fp, user_id)
    return {"success": True, "data": Gstr2bStatementOut.model_validate(statement)}


@router.post("/itc/reconcile")
async def reconcile_itc_data(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
    results = await reconcile_itc(session, gstin, fp)
    return {"success": True, "data": [ItcReconciliationOut.model_validate(r) for r in results]}
