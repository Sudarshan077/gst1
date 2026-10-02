"""Image/document preprocessing by capture_source branch.

Branches (EXTRACTION_SPEC.md §2):
  PDF_SCAN - deskew, denoise, 300 DPI normalize.
  DIGITAL  - native PDF text layer pass-through; image fallback treated as PHOTO.
  PHOTO    - auto-rotate, upscale/sharpen, blur check.
  WHATSAPP - same as PHOTO + stronger sharpening + multi-image assembly.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from typing import Any, NamedTuple

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageEnhance, ImageFilter

_LOGGER = logging.getLogger(__name__)


class PreprocessReport(NamedTuple):
    capture_source: str
    input_bytes: int
    output_bytes: int
    output_data: bytes | None
    output_mime_type: str
    pages: int
    blur_score: float | None
    blur_threshold: float
    blur_rejected: bool
    applied: list[str]


def _pil_to_cv(pil_img: Image.Image) -> np.ndarray:
    """Convert PIL RGB to OpenCV BGR."""
    return cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _laplacian_variance(pil_img: Image.Image) -> float:
    """Return Laplacian variance blur score; higher = sharper."""
    gray = cv2.cvtColor(_pil_to_cv(pil_img), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _deskew_image(pil_img: Image.Image) -> Image.Image:
    """Deskew via OpenCV min-area bounding box; return original on failure."""
    try:
        gray = cv2.cvtColor(_pil_to_cv(pil_img), cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(binary > 0))
        if len(coords) < 10:
            return pil_img
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) < 0.25:
            return pil_img
        h, w = gray.shape
        center = (w // 2, h // 2)
        mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            _pil_to_cv(pil_img), mat, (w, h),
            borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)
        )
        return _cv_to_pil(rotated)
    except Exception:
        return pil_img


def _normalize_dpi(pil_img: Image.Image, target_dpi: int = 300) -> Image.Image:
    """Resample to target DPI if current DPI is known and lower."""
    try:
        current_dpi = max(pil_img.info.get("dpi", (0, 0)))
        if 0 < current_dpi < target_dpi:
            factor = target_dpi / current_dpi
            new_size = (int(pil_img.width * factor), int(pil_img.height * factor))
            return pil_img.resize(new_size, Image.Resampling.LANCZOS)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("dpi normalization skipped: %s", exc)
    return pil_img


def _sharpen(pil_img: Image.Image, factor: float = 2.0) -> Image.Image:
    """Unsharp mask sharpen; factor > 1 means stronger."""
    sharpened = pil_img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    enhancer = ImageEnhance.Sharpness(sharpened)
    return enhancer.enhance(factor)


def _denoise(pil_img: Image.Image) -> Image.Image:
    """Fast non-local means denoise."""
    arr = _pil_to_cv(pil_img)
    denoised = cv2.fastNlMeansDenoisingColored(arr, None, 10, 10, 7, 21)
    return _cv_to_pil(denoised)


def _render_pdf_page_to_image(page: Any, dpi: int) -> Image.Image:
    """Render a PyMuPDF page to a PIL image at the requested DPI."""
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)  # type: ignore[no-untyped-call]
    pix = page.get_pixmap(matrix=mat)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _pil_bytes(pil_img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    pil_img.save(buf, format=fmt)
    return buf.getvalue()


def preprocess(
    data: bytes,
    mime_type: str,
    capture_source: str,
    *,
    dpi: int = 300,
    photo_blur_threshold: float = 80.0,
    whatsapp_blur_threshold: float = 60.0,
) -> PreprocessReport:
    """Preprocess one document according to its capture source.

    Returns a report containing the processed image bytes (single-page image or
    assembled PDF), blur score, and rejection flag. The caller still runs OCR.
    """
    applied: list[str] = []
    if mime_type == "application/pdf":
        doc: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        pages = len(doc)
        images: list[Image.Image] = []
        for page in doc:
            images.append(_render_pdf_page_to_image(page, dpi))
    else:
        images = [Image.open(io.BytesIO(data))]
        pages = 1

    source = capture_source.upper()
    blur_threshold = photo_blur_threshold
    if source == "WHATSAPP":
        blur_threshold = whatsapp_blur_threshold

    processed_images: list[Image.Image] = []
    for img in images:
        if source in {"PDF_SCAN"}:
            img = _deskew_image(img)
            img = _denoise(img)
            img = _normalize_dpi(img, dpi)
            applied.extend(["deskew", "denoise", "normalize_dpi"])
        elif source in {"PHOTO", "WHATSAPP"}:
            img = _deskew_image(img)
            img = _normalize_dpi(img, dpi)
            sharpen_factor = 3.0 if source == "WHATSAPP" else 2.0
            img = _sharpen(img, factor=sharpen_factor)
            applied.extend(["deskew", "normalize_dpi", "sharpen"])
        else:
            # DIGITAL / fallback
            img = _normalize_dpi(img, dpi)
            applied.append("normalize_dpi")
        processed_images.append(img)

    if len(processed_images) > 1:
        first = processed_images[0]
        rest = processed_images[1:]
        out_buf = io.BytesIO()
        first.convert("RGB").save(
            out_buf, "PDF", save_all=True,
            append_images=[im.convert("RGB") for im in rest], resolution=dpi
        )
        output_bytes = out_buf.getvalue()
        output_mime_type = "application/pdf"
    else:
        output_bytes = _pil_bytes(processed_images[0])
        output_mime_type = mime_type if mime_type.startswith("image") else "image/png"

    blur_score = _laplacian_variance(processed_images[0])
    blur_rejected = source in {"PHOTO", "WHATSAPP"} and blur_score < blur_threshold

    report = PreprocessReport(
        capture_source=source,
        input_bytes=len(data),
        output_bytes=len(output_bytes),
        output_data=output_bytes if output_bytes else None,
        output_mime_type=output_mime_type,
        pages=pages,
        blur_score=blur_score,
        blur_threshold=blur_threshold,
        blur_rejected=blur_rejected,
        applied=applied,
    )
    return report


def preprocess_many(
    parts: Sequence[tuple[str, bytes]],
    capture_source: str,
    *,
    dpi: int = 300,
    photo_blur_threshold: float = 80.0,
    whatsapp_blur_threshold: float = 60.0,
) -> PreprocessReport:
    """Preprocess multiple images and assemble into one PDF (photo bursts)."""
    if len(parts) == 1:
        return preprocess(
            parts[0][1],
            parts[0][0],
            capture_source,
            dpi=dpi,
            photo_blur_threshold=photo_blur_threshold,
            whatsapp_blur_threshold=whatsapp_blur_threshold,
        )

    images: list[Image.Image] = []
    for mime, data in parts:
        if mime == "application/pdf":
            doc: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
            for page in doc:
                images.append(_render_pdf_page_to_image(page, dpi))
        else:
            images.append(Image.open(io.BytesIO(data)))

    source = capture_source.upper()
    blur_threshold = photo_blur_threshold
    if source == "WHATSAPP":
        blur_threshold = whatsapp_blur_threshold

    processed: list[Image.Image] = []
    for img in images:
        img = _deskew_image(img)
        img = _normalize_dpi(img, dpi)
        sharpen_factor = 3.0 if source == "WHATSAPP" else 2.0
        img = _sharpen(img, factor=sharpen_factor)
        processed.append(img)

    first = processed[0]
    rest = processed[1:]
    out_buf = io.BytesIO()
    first.convert("RGB").save(
        out_buf, "PDF", save_all=True,
        append_images=[im.convert("RGB") for im in rest], resolution=dpi
    )
    output_bytes = out_buf.getvalue()

    blur_score = _laplacian_variance(processed[0])
    blur_rejected = source in {"PHOTO", "WHATSAPP"} and blur_score < blur_threshold

    return PreprocessReport(
        capture_source=source,
        input_bytes=sum(len(d) for _, d in parts),
        output_bytes=len(output_bytes),
        output_data=output_bytes if output_bytes else None,
        output_mime_type="application/pdf",
        pages=len(processed),
        blur_score=blur_score,
        blur_threshold=blur_threshold,
        blur_rejected=blur_rejected,
        applied=["deskew", "normalize_dpi", "sharpen", "assemble_pdf"],
    )
