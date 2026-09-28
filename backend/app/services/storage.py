"""MinIO document storage: upload, presigned GET, sha256 dedupe helpers.

Bucket layout follows SECURITY_AND_ACCESS.md §3:
  keys = {gstin}/{fp}/{docId}
No public buckets; presigned URLs expire in 30 minutes.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pymupdf
from app.api.errors import ServiceError
from app.config import Settings, get_settings
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error
from PIL import Image

_LOGGER = __import__("logging").getLogger(__name__)

_BUCKET = "gst-docs"
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # API_SPEC §5: 25 MB/file
_PRESIGNED_MINUTES = 30

# Magic-byte signatures we accept for uploads (SECURITY §6: magic-byte check).
_MAGIC: dict[bytes, str] = {
    b"%PDF": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
}


def _minio_client() -> Minio:
    settings = get_settings()
    endpoint = settings.minio_endpoint or "127.0.0.1:9001"
    use_ssl = settings.minio_use_tls
    access_key = settings.minio_access_key or "gst_admin"
    secret_key = settings.minio_secret_key or "gst_minio_dev_pass"
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=use_ssl)


def _detect_mime(data: bytes) -> str | None:
    for sig, mime in _MAGIC.items():
        if data.startswith(sig):
            return mime
    return None


def _object_key(gstin: str, fp: str, doc_id: uuid.UUID, version: int = 1) -> str:
    return f"{gstin}/{fp}/{doc_id}_v{version}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_count(data: bytes, mime: str) -> int | None:
    if mime == "application/pdf":
        try:
            doc: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
            return int(len(doc))
        except Exception:
            return None
    if mime in {"image/jpeg", "image/png"}:
        return 1
    return None


def _resize_image(data: bytes, max_px: int = 4096) -> bytes:
    """Return a downscaled copy if an image exceeds max_px on either axis."""
    try:
        img = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ServiceError("undecodable image", 422, "VALIDATION_ERROR") from exc
    try:
        if img.width > max_px or img.height > max_px:
            img.thumbnail((max_px, max_px))
            out_fmt = img.format or "JPEG"
            buf = io.BytesIO()
            img.save(buf, format=out_fmt, quality=85)
            return buf.getvalue()
        return data
    except Exception as exc:
        raise ServiceError("undecodable image", 422, "VALIDATION_ERROR") from exc


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    await file.seek(0)
    return data


async def build_document(
    *,
    files: Sequence[UploadFile],
    capture_source: str,
) -> dict[str, Any]:
    """Read, magic-check, resize/merge and return the final payload.

    No MinIO I/O here — this is pure byte preprocessing so dedupe can run
    against the processed sha256 before any object is stored.
    """
    if not files:
        raise ServiceError("no files uploaded", 422, "VALIDATION_ERROR")

    if len(files) > 1 and capture_source not in {"PHOTO", "WHATSAPP"}:
        raise ServiceError("multiple files allowed only for photo bursts", 422, "VALIDATION_ERROR")

    is_photo_burst = capture_source in {"PHOTO", "WHATSAPP"} and len(files) > 1
    parts: list[tuple[str, bytes]] = []
    for file in files:
        data = await _read_upload(file)
        if len(data) > _MAX_UPLOAD_BYTES:
            raise ServiceError("file exceeds 25 MB limit", 422, "VALIDATION_ERROR")
        mime = _detect_mime(data)
        if mime is None:
            raise ServiceError("unsupported file type", 422, "VALIDATION_ERROR")
        if mime in {"image/jpeg", "image/png"}:
            data = _resize_image(data)
        parts.append((mime, data))

    if is_photo_burst:
        merged = _merge_images_to_pdf(parts)
        final_mime = "application/pdf"
        page_count = _page_count(merged, final_mime)
    else:
        final_mime, merged = parts[0]
        page_count = _page_count(merged, final_mime)

    if final_mime == "application/pdf" and page_count is None:
        raise ServiceError("unable to parse document pages", 422, "VALIDATION_ERROR")

    settings = get_settings()
    if page_count is not None and page_count > settings.max_document_pages:
        raise ServiceError("document exceeds page limit", 422, "VALIDATION_ERROR")

    sha256_hash = _sha256(merged)
    return {
        "payload": merged,
        "sha256": sha256_hash,
        "bytes": len(merged),
        "page_count": page_count,
        "mime_type": final_mime,
    }


async def upload_document(
    *,
    gstin: str,
    fp: str,
    doc_id: uuid.UUID,
    built: dict[str, Any],
    uploaded_by: uuid.UUID,
) -> dict[str, Any]:
    """Persist a pre-built document payload to MinIO.

    Keys: {gstin}/{fp}/{docId}. Object content_type carries the MIME.
    """
    merged = built["payload"]
    sha256_hash = built["sha256"]
    final_mime = built["mime_type"]
    page_count = built["page_count"]
    key = _object_key(gstin, fp, doc_id)
    client = _minio_client()
    if not client.bucket_exists(_BUCKET):
        client.make_bucket(_BUCKET)
    client.put_object(
        _BUCKET,
        key,
        data=io.BytesIO(merged),
        length=len(merged),
        content_type=final_mime,
        metadata={
            "x-amz-meta-sha256": sha256_hash,
            "x-amz-meta-uploaded-by": str(uploaded_by),
        },
    )
    return {
        "minio_key": key,
        "sha256": sha256_hash,
        "bytes": len(merged),
        "page_count": page_count,
    }


def _merge_images_to_pdf(parts: list[tuple[str, bytes]]) -> bytes:
    """Convert a sequence of image bytes into a single PDF byte stream."""
    images: list[Any] = []
    for _, data in parts:
        try:
            img: Any = Image.open(io.BytesIO(data))
        except Exception as exc:
            raise ServiceError("undecodable image", 422, "VALIDATION_ERROR") from exc
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        images.append(img)
    if not images:
        raise ServiceError("empty photo burst", 422, "VALIDATION_ERROR")
    first: Any = images[0]
    rest: list[Any] = images[1:]
    out = io.BytesIO()
    try:
        first.save(out, "PDF", save_all=True, append_images=rest, resolution=100.0)
    except Exception as exc:
        raise ServiceError("undecodable image", 422, "VALIDATION_ERROR") from exc
    return out.getvalue()


def presigned_view_url(minio_key: str, minutes: int = _PRESIGNED_MINUTES) -> str:
    """Return a 30-min presigned GET URL for the stored object."""
    client = _minio_client()
    try:
        return client.presigned_get_object(
            _BUCKET, minio_key, expires=timedelta(minutes=minutes)
        )
    except S3Error as exc:
        raise ServiceError(str(exc), 404, "NOT_FOUND") from exc


def remove_object(bucket: str, minio_key: str) -> None:
    """Compensating delete for stored objects; swallows NOT_FOUND."""
    client = _minio_client()
    try:
        client.remove_object(bucket, minio_key)
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            _LOGGER.warning("remove_object failed for %s/%s: %s", bucket, minio_key, exc)


# Re-export typed helper for tests/monkeypatching.
Settings = Settings
