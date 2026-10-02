"""Document router: upload, list, detail, presigned view (API_SPEC §5).

v4.0 (TECHNICAL_ARCHITECTURE §3): documents hang off the GSTIN, so the
collection routes are `/gst-accounts/{gstin}/months/{fp}/documents`. Routes
keyed by `doc_id` resolve the document first and then re-run the same guard
against that document's GSTIN — a cross-tenant doc id must resolve to 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DraftFieldUpdateIn, RejectIn
from app.core.access import (
    GstinAccess,
    require_gstin_access,
    resolve_gstin_access,
)
from app.core.auth.dependencies import require_user
from app.db.session import get_session
from app.services.documents import (
    get_document,
    get_document_detail,
    list_documents,
    store_documents,
)
from app.services.review import (
    confirm_draft,
    get_draft,
    get_review_queue,
    reject_document,
    update_draft,
)
from app.services.storage import presigned_view_url

router = APIRouter(tags=["documents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

_REVIEW_WRITE = "document review requires FILER or ADMIN on the GSTIN"
_ALLOWED_DOC_TYPES = {"UNCLASSIFIED", "INV", "CDN", "DBN", "OTHER"}


async def _doc_access(
    session: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID
) -> tuple[Any, GstinAccess]:
    """Resolve a document by id and guard it against its own GSTIN."""
    doc = await get_document(session, doc_id)
    access = await resolve_gstin_access(session, user_id, doc.gstin)
    return doc, access


@router.get("/gst-accounts/{gstin}/months/{fp}/review-queue")
async def review_queue(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
) -> dict[str, Any]:
    rows = await get_review_queue(session, access, fp)
    return {"success": True, "data": rows}


@router.get("/documents/{doc_id}/draft")
async def get_doc_draft(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    data = await get_draft(session, doc_id, access)
    return {"success": True, "data": data}


@router.put("/documents/{doc_id}/draft")
async def put_doc_draft(
    doc_id: uuid.UUID,
    body: DraftFieldUpdateIn,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    if not access.can_write:
        from app.core.access import PermissionDenied

        raise PermissionDenied(_REVIEW_WRITE)
    data = await update_draft(session, doc_id, access, user_id, body.model_dump(exclude_unset=True))
    return {"success": True, "data": data}


@router.post("/documents/{doc_id}/confirm")
async def confirm_doc(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    if not access.can_write:
        from app.core.access import PermissionDenied

        raise PermissionDenied(_REVIEW_WRITE)
    data = await confirm_draft(session, doc_id, access, user_id)
    return {"success": True, "data": data}


@router.post("/documents/{doc_id}/reject")
async def reject_doc(
    doc_id: uuid.UUID,
    body: RejectIn,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    if not access.can_write:
        from app.core.access import PermissionDenied

        raise PermissionDenied(_REVIEW_WRITE)
    data = await reject_document(session, doc_id, access, user_id, body.reason)
    return {"success": True, "data": data}


@router.post("/gst-accounts/{gstin}/months/{fp}/documents")
async def upload_documents(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    user_id: UserDep,
    capture_source: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    doc_type: Annotated[str, Form()] = "UNCLASSIFIED",
) -> dict[str, Any]:
    if len(doc_type) > 16 or doc_type not in _ALLOWED_DOC_TYPES:
        from app.api.errors import ServiceError

        raise ServiceError("invalid doc_type", 422, "VALIDATION_ERROR")
    if not access.can_write:
        from app.core.access import PermissionDenied

        raise PermissionDenied("upload requires FILER or ADMIN on the GSTIN")
    result = await store_documents(
        session,
        access=access,
        fp=fp,
        files=files,
        capture_source=capture_source,
        doc_type=doc_type,
        uploaded_by=user_id,
    )
    return {"success": True, "data": result}


@router.get("/gst-accounts/{gstin}/months/{fp}/documents")
async def list_docs(
    gstin: str,
    fp: str,
    access: Annotated[GstinAccess, Depends(require_gstin_access("gstin"))],
    session: SessionDep,
    page: Annotated[int, Query(ge=0)] = 0,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    rows, total = await list_documents(session, access, fp, page=page, size=size)
    return {
        "success": True,
        "data": {
            "content": rows,
            "page": page,
            "size": size,
            "totalElements": total,
            "last": (page + 1) * size >= total,
        },
    }


@router.get("/documents/{doc_id}")
async def get_doc(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    detail = await get_document_detail(session, doc_id, access)
    return {"success": True, "data": detail}


@router.get("/documents/{doc_id}/image")
async def get_doc_image(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict[str, Any]:
    _doc, access = await _doc_access(session, user_id, doc_id)
    detail = await get_document_detail(session, doc_id, access)
    page_count = detail["page_count"] or 1
    if page > page_count:
        from app.api.errors import ServiceError

        raise ServiceError("page exceeds document page count", 422, "VALIDATION_ERROR")
    url = presigned_view_url(detail["minio_key"])
    return {
        "success": True,
        "data": {
            "presigned_url": url,
            "expires_in_minutes": 30,
            "page": page,
            "page_count": page_count,
        },
    }
