"""Tests for document upload, storage, presigned URLs, and dedupe.

Covers API_SPECIFICATION.md §5 + SECURITY_AND_ACCESS.md §3/§6.
Requires live PG at :5436 and MinIO at :9001 (bootstrap_stack.py).
"""

from __future__ import annotations

import io
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from app.core.auth.tokens import verify_access_token
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_mobile, register_and_login
from tests.v4_helpers import seed_gstin_for_user


@pytest.fixture()
def minimal_pdf() -> bytes:
    """Small valid PDF byte sequence."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        b"2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n"
        b"3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n"
        b"0000000058 00000 n\n0000000115 00000 n\n"
        b"trailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n196\n%%EOF"
    )


async def test_upload_pdf_stores_versioned_doc(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """POST multipart PDF -> 200, DB row + MinIO key {gstin}/{fp}/{docId}."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="27")
    gstin, fp = account.gstin, "092026"

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("invoice.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["sha256"] is not None
    assert data["minio_key"] == f"{gstin}/{fp}/{data['id']}_v1"
    assert data["doc_type"] == "UNCLASSIFIED"
    assert data["page_count"] == 1


async def test_photo_burst_merge(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Multi-file PHOTO burst -> merged PDF stored as one doc."""
    from PIL import Image

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="29")
    gstin, fp = account.gstin, "092026"

    def make_image(name: str, colour: tuple[int, int, int]) -> tuple[str, io.BytesIO, str]:
        img = Image.new("RGB", (100, 100), colour)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return (name, buf, "image/png")

    files = [
        ("files", make_image("a.png", (255, 0, 0))),
        ("files", make_image("b.png", (0, 255, 0))),
    ]
    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PHOTO"},
        files=files,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["doc_type"] == "UNCLASSIFIED"
    assert data["page_count"] == 2


async def test_upload_rejects_bad_magic_byte(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Files without recognized magic bytes return 422."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="07")
    gstin, fp = account.gstin, "092026"

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("evil.exe", io.BytesIO(b"MZ..."), "application/pdf")},
    )
    assert response.status_code == 422
    assert "unsupported" in response.json()["error"]["message"].lower()


async def test_upload_rejects_oversized(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Files > 25 MB return 422."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="06")
    gstin, fp = account.gstin, "092026"

    big = b"%PDF" + b"0" * (26 * 1024 * 1024)
    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("big.pdf", io.BytesIO(big), "application/pdf")},
    )
    assert response.status_code == 422
    assert "25" in response.json()["error"]["message"]


async def test_duplicate_upload_rejected(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """Second upload of the exact same bytes returns 422 dedupe error."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="24")
    gstin, fp = account.gstin, "092026"

    for _ in range(2):
        response = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PDF_SCAN"},
            files={"files": ("dup.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "duplicate" in response.json()["error"]["message"].lower()


async def test_duplicate_after_resize_rejected(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Same oversized PNG twice: resize produces identical bytes, second 422."""
    from PIL import Image

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="33")
    gstin, fp = account.gstin, "092026"

    # one dimension exceeds 4096, so the service resizes deterministically.
    img = Image.new("RGB", (5000, 100), (0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    image_bytes = buf.read()

    for _ in range(2):
        response = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PHOTO"},
            files={"files": ("big.png", io.BytesIO(image_bytes), "image/png")},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "duplicate" in response.json()["error"]["message"].lower()


async def test_photo_burst_with_pdf_frame_422(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """PHOTO burst with a PDF frame is not allowed; 422."""
    from PIL import Image

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="11")
    gstin, fp = account.gstin, "092026"

    img = Image.new("RGB", (100, 100), (255, 0, 0))
    png_buf = io.BytesIO()
    img.save(png_buf, format="PNG")
    png_buf.seek(0)

    files = [
        ("files", ("frame.png", png_buf, "image/png")),
        ("files", ("frame.pdf", io.BytesIO(minimal_pdf), "application/pdf")),
    ]
    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PHOTO"},
        files=files,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_undecodable_jpeg_422(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """JPEG magic prefix followed by garbage returns 422, not a PIL traceback."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="12")
    gstin, fp = account.gstin, "092026"

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PHOTO"},
        files={"files": ("bad.jpg", io.BytesIO(b"\xff\xd8\xff" + b"garbage"), "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_page_cap_rejected(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """2-image burst with max_document_pages=1 should fail with 422."""
    from app.config import get_settings
    from PIL import Image

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="14")
    gstin, fp = account.gstin, "092026"

    real_cap = get_settings().max_document_pages
    get_settings().max_document_pages = 1
    try:
        def make_image(name: str, colour: tuple[int, int, int]) -> tuple[str, io.BytesIO, str]:
            img = Image.new("RGB", (100, 100), colour)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return (name, buf, "image/png")

        files = [
            ("files", make_image("a.png", (255, 0, 0))),
            ("files", make_image("b.png", (0, 255, 0))),
        ]
        response = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PHOTO"},
            files=files,
        )
        assert response.status_code == 422
        assert "page" in response.json()["error"]["message"].lower()
    finally:
        get_settings().max_document_pages = real_cap


async def test_presigned_url_30_min(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """GET /documents/{docId}/image returns a presigned URL with ~30-min expiry."""

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="27")
    gstin, fp = account.gstin, "092026"

    upload_resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("view.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["data"]["id"]

    response = await client.get(f"/api/v1/documents/{doc_id}/image", headers=headers)
    assert response.status_code == 200, response.text
    url = response.json()["data"]["presigned_url"]
    parsed = urlparse(url)
    assert parsed.netloc
    assert parse_qs(parsed.query)["X-Amz-Expires"] == ["1800"]


async def test_image_page_param(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """?page=1 succeeds; ?page=2 on a 1-page doc returns 422."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="27")
    gstin, fp = account.gstin, "092026"

    upload_resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("page.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["data"]["id"]

    r1 = await client.get(f"/api/v1/documents/{doc_id}/image?page=1", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["data"]["page"] == 1

    r2 = await client.get(f"/api/v1/documents/{doc_id}/image?page=2", headers=headers)
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_upload_requires_auth(
    client: AsyncClient,
) -> None:
    """Unauthenticated POST returns 401."""
    response = await client.post(
        "/api/v1/gst-accounts/00AAAAAAAAAAAAAAA/months/092026/documents",
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert response.status_code == 401


async def test_upload_cross_tenant_returns_404(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Uploader with no access to the GSTIN gets 404 (existence hidden)."""
    owner = await register_and_login(client, make_mobile())
    user_id = verify_access_token(owner["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="27")
    gstin, fp = account.gstin, "092026"

    # Create a second user who has no access to the GSTIN above.
    attacker = await register_and_login(client, make_mobile())
    attacker_headers = {"Authorization": f"Bearer {attacker['access_token']}"}
    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=attacker_headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GSTIN_NOT_FOUND"


async def test_doc_detail_cross_tenant_returns_404(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """Owner-access {doc_id} test: other user cannot GET /documents/{docId}."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}  # owner
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="27")
    gstin, fp = account.gstin, "092026"

    upload_resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("owner.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["data"]["id"]

    attacker = await register_and_login(client, make_mobile())
    attacker_headers = {"Authorization": f"Bearer {attacker['access_token']}"}
    response = await client.get(f"/api/v1/documents/{doc_id}", headers=attacker_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GSTIN_NOT_FOUND"


async def test_multifile_non_burst_rejected_422(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """2 PNGs with capture_source=PDF_SCAN must be rejected; nothing stored."""
    from PIL import Image

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="09")
    gstin, fp = account.gstin, "092026"

    def make_image(name: str, colour: tuple[int, int, int]) -> tuple[str, io.BytesIO, str]:
        img = Image.new("RGB", (100, 100), colour)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return (name, buf, "image/png")

    files = [
        ("files", make_image("a.png", (255, 0, 0))),
        ("files", make_image("b.png", (0, 255, 0))),
    ]

    async with api_sessionmaker() as session:
        before = (
            await session.execute(
                text("SELECT count(*) FROM extraction.documents")
            )
        ).scalar_one()

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files=files,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "photo burst" in response.json()["error"]["message"].lower()

    async with api_sessionmaker() as session:
        after = (
            await session.execute(
                text("SELECT count(*) FROM extraction.documents")
            )
        ).scalar_one()
        assert after == before


async def test_sha256_unique_index_exists(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """The migration created the unique index on (gstin, fp, sha256)."""

    async with api_sessionmaker() as session:
        indexdef = (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname='extraction' "
                    "AND indexname='uq_documents_gstin_fp_sha256'"
                )
            )
        ).scalar_one()
        assert "UNIQUE" in indexdef
        assert "gstin" in indexdef
        assert "fp" in indexdef
        assert "sha256" in indexdef


async def test_duplicate_upload_rejected_single_process_409(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """Single-process duplicate upload hits the unique index and returns 409."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="08")
    gstin, fp = account.gstin, "092026"

    for _ in range(2):
        response = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PDF_SCAN"},
            files={"files": ("dup.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_concurrent_period_create_race_safe(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """Two sessions racing to create the same period: 0x500, exactly 1 row."""
    import asyncio


    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="05")
    gstin, fp = account.gstin, "092026"

    async def upload() -> int:
        resp = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PDF_SCAN"},
            files={"files": ("race.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        return resp.status_code

    statuses = await asyncio.gather(upload(), upload())
    internal_errors = [s for s in statuses if s == 500]
    assert len(internal_errors) == 0, statuses
    assert set(statuses) in ({200, 409}, {409})

    async with api_sessionmaker() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM gst.filing_periods "
                    "WHERE gstin=:rid AND fp=:fp"
                ).bindparams(rid=gstin, fp=fp)
            )
        ).scalar_one()
        assert count == 1


async def test_unparseable_pdf_422_and_no_rows_stored(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
) -> None:
    """Magic-byte-valid PDF that pymupdf cannot parse returns 422."""

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="03")
    gstin, fp = account.gstin, "092026"

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("bad.pdf", io.BytesIO(b"%PDF-1.4\nbroken"), "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    async with api_sessionmaker() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM extraction.documents "
                    "WHERE gstin=:rid AND fp=:fp"
                ).bindparams(rid=gstin, fp=fp)
            )
        ).scalar_one()
        assert count == 0


async def test_pagination_fields_present(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
) -> None:
    """GET list returns the pagination envelope per API_SPEC §15."""
    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="02")
    gstin, fp = account.gstin, "092026"

    # Upload two docs; second must differ to avoid dedupe.
    for i in range(2):
        response = await client.post(
            f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
            headers=headers,
            data={"capture_source": "PDF_SCAN"},
            files={"files": (f"p{i}.pdf", io.BytesIO(minimal_pdf + bytes([i])), "application/pdf")},
        )
        assert response.status_code == 200

    response = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents?page=0&size=1",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["page"] == 0
    assert payload["size"] == 1
    assert payload["totalElements"] == 2
    assert payload["last"] is False
    assert len(payload["content"]) == 1

    page2 = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents?page=1&size=1",
        headers=headers,
    )
    assert page2.status_code == 200
    payload2 = page2.json()["data"]
    assert payload2["page"] == 1
    assert payload2["last"] is True
    assert len(payload2["content"]) == 1
    # page 0 and page 1 should return different document ids.
    assert payload["content"][0]["id"] != payload2["content"][0]["id"]


async def test_orphan_object_compensating_delete(
    client: AsyncClient,
    api_sessionmaker: async_sessionmaker[Any],
    minimal_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forced DB commit failure after MinIO put leaves 0 objects for that prefix."""
    from app.services import documents as documents_module
    from app.services.storage import _minio_client, remove_object
    from minio import Minio

    tokens = await register_and_login(client, make_mobile())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = verify_access_token(tokens["access_token"])
    account = await seed_gstin_for_user(api_sessionmaker, user_id, state_code="01")
    gstin, fp = account.gstin, "092026"


    calls = 0

    async def fake_commit(self: Any) -> None:
        nonlocal calls
        calls += 1
        raise IntegrityError("forced commit failure", params=None, orig=RuntimeError("boom"))

    monkeypatch.setattr(documents_module.AsyncSession, "commit", fake_commit)  # type: ignore[attr-defined]

    response = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/documents",
        headers=headers,
        data={"capture_source": "PDF_SCAN"},
        files={"files": ("orphan.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"

    client_minio: Minio = _minio_client()
    prefix = f"{gstin}/{fp}/"
    objects = list(client_minio.list_objects("gst-docs", prefix=prefix, recursive=True))
    # No objects for this registration/fp prefix after compensating delete.
    assert len(objects) == 0
    # Sanity check: remove_object helper exists and is callable.
    assert callable(remove_object)
