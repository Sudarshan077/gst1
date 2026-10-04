import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import GstinAccess, require_gstin_access, audit
from app.core.auth.dependencies import require_user
from app.db.models.gst import ExportType, FilingPeriod, FilingStatus, Gstr1Export
from app.db.session import get_session
from app.services.returns.gstr1a import create_gstr1a_amendments
from app.services.returns.gsp_adapter import file_gstr1_gsp, file_gstr3b_gsp

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

router = APIRouter(prefix="/gst-accounts/{gstin}/months/{fp}", tags=["returns"])

@router.post("/gstr1/prepare")
async def prepare_gstr1(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    await audit(session, action="GSTR1_PREPARE", entity="return", entity_id=f"{gstin}-{fp}", actor_user_id=user_id, gstin=gstin)
    return {"success": True, "data": {"summary": "OK"}}

@router.post("/gstr1/generate")
async def generate_gstr1(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    # Create Gstr1Export record
    export = Gstr1Export(
        gstin=gstin,
        fp=fp,
        generated_by=user_id,
        json_minio_key=f"gstr1/{gstin}/{fp}/export.json",
        invoice_count=0,
        totals={},
        schema_version="1.0",
        export_type=ExportType.ORIGINAL,
    )
    session.add(export)
    await audit(session, action="GSTR1_GENERATE", entity="return", entity_id=str(export.id), actor_user_id=user_id, gstin=gstin)
    await session.commit()
    return {"success": True, "data": {"export_id": str(export.id)}}

@router.post("/filed")
async def file_return(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    period = await session.get(FilingPeriod, (gstin, fp))
    if period is None:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="REGULAR_MONTHLY",
            status=FilingStatus.FILED,
            filed_at=datetime.utcnow(),
            filed_by=user_id,
        )
        session.add(period)
    else:
        period.status = FilingStatus.FILED
        period.filed_at = datetime.utcnow()
        period.filed_by = user_id
    await audit(session, action="RETURN_FILED", entity="return", entity_id=f"{gstin}-{fp}", actor_user_id=user_id, gstin=gstin)
    await session.commit()
    return {"success": True, "data": {"status": "FILED"}}

@router.post("/gstr4/prepare")
async def prepare_gstr4(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
    return {"success": True, "data": {"summary": "OK"}}

@router.post("/gstr4/filed")
async def file_gstr4(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    period = await session.get(FilingPeriod, (gstin, fp))
    if period is None:
        period = FilingPeriod(
            gstin=gstin,
            fp=fp,
            scheme_snapshot="COMPOSITION",
            status=FilingStatus.FILED,
            filed_at=datetime.utcnow(),
            filed_by=user_id,
        )
        session.add(period)
    else:
        period.status = FilingStatus.FILED
        period.filed_at = datetime.utcnow()
        period.filed_by = user_id
    await session.commit()
    return {"success": True, "data": {"status": "FILED"}}


@router.post("/gsp/gstr1/file")
async def file_gstr1_via_gsp(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    res = await file_gstr1_gsp(session, gstin, fp, user_id)
    return {"success": True, "data": res}


@router.post("/gsp/gstr3b/file")
async def file_gstr3b_via_gsp(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
) -> dict[str, Any]:
    res = await file_gstr3b_gsp(session, gstin, fp, user_id)
    return {"success": True, "data": res}


