"""Tests for capture-source preprocessing branches and blur rejection."""

from __future__ import annotations

import io

from app.extraction.preprocess import preprocess, preprocess_many
from PIL import Image


def _image_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_pdf_scan_preprocess_deskew_denoise() -> None:
    # Use a tiny valid PDF for preprocess branch coverage.
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        b"2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n"
        b"3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n"
        b"0000000058 00000 n\n0000000115 00000 n\n"
        b"trailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n196\n%%EOF"
    )
    report = preprocess(pdf, "application/pdf", "PDF_SCAN", dpi=150)
    assert report.capture_source == "PDF_SCAN"
    assert report.pages == 1
    assert "deskew" in report.applied
    assert "denoise" in report.applied
    assert not report.blur_rejected


def test_digital_preprocess_normalizes_dpi() -> None:
    img = Image.new("RGB", (200, 100), "white")
    data = _image_bytes(img)
    report = preprocess(data, "image/png", "DIGITAL", dpi=150)
    assert "normalize_dpi" in report.applied
    assert not report.blur_rejected


def test_photo_blur_rejected() -> None:
    # Solid color is extremely blurry
    img = Image.new("RGB", (100, 100), "gray")
    data = _image_bytes(img)
    report = preprocess(
        data, "image/png", "PHOTO", dpi=150,
        photo_blur_threshold=100.0, whatsapp_blur_threshold=100.0
    )
    assert report.blur_rejected
    assert report.capture_source == "PHOTO"


def test_photo_sharp_passes() -> None:
    # Random noise is sharp but not realistic; acceptable for blur gate testing.
    import numpy as np
    arr = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    data = _image_bytes(img)
    report = preprocess(
        data, "image/png", "PHOTO", dpi=150,
        photo_blur_threshold=10.0, whatsapp_blur_threshold=5.0
    )
    assert not report.blur_rejected
    assert "sharpen" in report.applied


def test_whatsapp_stronger_sharpen() -> None:
    import numpy as np
    arr = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    data = _image_bytes(img)
    report = preprocess(
        data, "image/png", "WHATSAPP", dpi=150,
        photo_blur_threshold=10.0, whatsapp_blur_threshold=5.0
    )
    assert not report.blur_rejected
    assert "sharpen" in report.applied


def test_preprocess_many_assembles_pdf() -> None:
    import numpy as np
    parts: list[tuple[str, bytes]] = []
    for colour in [(255, 0, 0), (0, 255, 0)]:
        arr = np.full((100, 100, 3), colour, dtype=np.uint8)
        img = Image.fromarray(arr)
        parts.append(("image/png", _image_bytes(img)))
    report = preprocess_many(
        parts, "WHATSAPP", dpi=150,
        photo_blur_threshold=5.0, whatsapp_blur_threshold=5.0
    )
    assert report.pages == 2
    assert report.output_bytes > 0
    assert "assemble_pdf" in report.applied


def test_invalid_capture_source_normalizes() -> None:
    img = Image.new("RGB", (100, 100), "white")
    data = _image_bytes(img)
    report = preprocess(data, "image/png", "pdf_scan", dpi=150)
    assert report.capture_source == "PDF_SCAN"
