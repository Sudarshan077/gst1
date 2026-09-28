"""Document router: upload, list, detail, presigned view (API_SPEC §5)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    RegistrationAccess,
    require_registration_access,
    resolve_registration_access,
)
from app.core.auth.dependencies import require_user
from app.db.session import get_session
from app.services.documents import (
    get_document,
    get_document_detail,
    list_documents,
    store_documents,
)
from app.services.storage import presigned_view_url

router = APIRouter(tags=["documents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[uuid.UUID, Depends(require_user)]

_ALLOWED_DOC_TYPES = {"UNCLASSIFIED", "INV", "CDN", "DBN", "OTHER"}


@router.post("/registrations/{registration_id}/months/{fp}/documents")
async def upload_documents(
    registration_id: str,
    fp: str,
    access: Annotated[RegistrationAccess, Depends(require_registration_access("registration_id"))],
    session: SessionDep,
    user_id: UserDep,
    capture_source: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    doc_type: Annotated[str, Form()] = "UNCLASSIFIED",
) -> dict[str, Any]:
    if len(doc_type) > 16 or doc_type not in _ALLOWED_DOC_TYPES:
        from app.api.errors import ServiceError
        raise ServiceError("invalid doc_type", 422, "VALIDATION_ERROR")
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


@router.get("/registrations/{registration_id}/months/{fp}/documents")
async def list_docs(
    registration_id: str,
    fp: str,
    access: Annotated[RegistrationAccess, Depends(require_registration_access("registration_id"))],
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
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
            "last": page * size >= total,
        },
    }


@router.get("/documents/{doc_id}")
async def get_doc(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
) -> dict[str, Any]:
    doc = await get_document(session, doc_id)
    access = await resolve_registration_access(session, user_id, doc.registration_id)
    detail = await get_document_detail(session, doc_id, access)
    return {"success": True, "data": detail}


@router.get("/documents/{doc_id}/image")
async def get_doc_image(
    doc_id: uuid.UUID,
    user_id: UserDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict[str, Any]:
    doc = await get_document(session, doc_id)
    access = await resolve_registration_access(session, user_id, doc.registration_id)
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
