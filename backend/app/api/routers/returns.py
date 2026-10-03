import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import GstinAccess, require_gstin_access
from app.core.auth.dependencies import require_user
from app.db.models.gst import ExportType, FilingPeriod, FilingStatus, Gstr1Export
from app.db.session import get_session
from app.services.returns.gstr1a import create_gstr1a_amendments

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

router = APIRouter(prefix="/gst-accounts/{gstin}/months/{fp}", tags=["returns"])

@router.post("/gstr1/prepare")
async def prepare_gstr1(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
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
    await session.commit()
    return {"success": True, "data": {"status": "FILED"}}

@router.post("/gstr1a")
async def gstr1a_amendments(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    body: dict[str, Any],
) -> dict[str, Any]:
    amendments = await create_gstr1a_amendments(session, gstin, fp, body)
    return {"success": True, "data": {"amendments": amendments, "status": "AMENDED"}}
