"""Tests for extraction pipeline (preprocess → OCR → LLM → validate).

Uses mocked OCR and LLM so no external services are required.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from app.config import Settings
from app.extraction.llm import LLMClient, LLMExtractionError
from app.extraction.models import CaptureSource
from app.extraction.ocr import EmptyOCRError
from app.extraction.pipeline import run_pipeline
from app.extraction.preprocess import PreprocessReport
from PIL import Image

from tests.gstin_fixtures import make_gstin, make_pan


@pytest.fixture()
def settings() -> Settings:
    s = Settings()
    s.extraction_blur_threshold_photo = 10.0  # very low so normal images pass
    s.extraction_blur_threshold_whatsapp = 5.0
    s.extraction_ocr_dpi = 150
    return s


@pytest.fixture()
def invoice_image() -> bytes:
    """A synthetic invoice-like image (text is not real, but readable enough for tests)."""
    img = Image.new("RGB", (400, 200), "white")
    return _image_bytes(img)


def _image_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ocr_stub(text: str) -> Any:
    def _ocr(_image: Image.Image) -> str:
        return text
    return _ocr


class _FakeLLMClient(LLMClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.model = "test-model"

    async def extract(self, ocr_text: str) -> dict[str, Any]:
        return self.payload


def _llm_payload(
    *,
    supplier_gstin: str | None = None,
    buyer_gstin: str | None = None,
    invoice_no: str = "INV-2025-0042",
    invoice_date: str = "2025-05-04",
    place_of_supply: str = "27",
    is_inter_state: bool = False,
    rchrg: bool = False,
    inv_typ: str = "R",
    taxable_value_paise: int = 1500000,
    total_value_paise: int = 1770000,
    cgst_paise: int = 135000,
    sgst_paise: int = 135000,
    igst_paise: int = 0,
    cess_paise: int = 0,
    confidence: dict[str, float] | None = None,
) -> dict[str, Any]:
    if supplier_gstin is None:
        supplier_gstin = make_gstin(pan=make_pan(), state_code="27")
    return {
        "doc_id": invoice_no,
        "capture_source": "PDF_SCAN",
        "fields": {
            "supplier_gstin": supplier_gstin,
            "buyer_gstin": buyer_gstin,
            "invoice_no": invoice_no,
            "invoice_date": invoice_date,
            "place_of_supply": place_of_supply,
            "is_inter_state": is_inter_state,
            "rchrg": rchrg,
            "inv_typ": inv_typ,
            "taxable_value_paise": taxable_value_paise,
            "total_value_paise": total_value_paise,
            "cgst_paise": cgst_paise,
            "sgst_paise": sgst_paise,
            "igst_paise": igst_paise,
            "cess_paise": cess_paise,
        },
        "lines": [],
        "confidence": confidence or {
            "supplier_gstin": 0.99, "invoice_no": 0.99, "invoice_date": 0.99,
            "place_of_supply": 0.99, "is_inter_state": 0.99, "rchrg": 0.99,
            "inv_typ": 0.99, "taxable_value_paise": 0.99, "total_value_paise": 0.99,
            "cgst_paise": 0.99, "sgst_paise": 0.99, "igst_paise": 0.99,
            "cess_paise": 0.99,
        },
        "_llm_meta": {"model": "test-model", "tokens_in": 100, "tokens_out": 200},
    }


async def test_pipeline_passes_preprocessed_bytes_to_ocr(settings: Settings) -> None:
    """Preprocessed image bytes must reach OCR, not raw bytes."""
    import numpy as np

    arr = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    data = _image_bytes(img)

    seen: dict[str, Any] = {}

    def _ocr(image: Image.Image) -> str:
        seen["image"] = image
        return "GSTIN 27AABCU9603R1ZM Invoice INV-2025-0042 Date 04/05/2025"

    result = await run_pipeline(
        data,
        "image/png",
        "PHOTO",
        doc_id="DOC-P",
        ocr_provider=_ocr,
        llm_client=_FakeLLMClient(_llm_payload()),
        settings=settings,
    )
    assert result.error is None
    assert result.document is not None
    assert "image" in seen
    processed_bytes = _image_bytes(seen["image"])
    assert processed_bytes != data, "OCR must receive the preprocessed image, not raw data"

    assert result.preproc_report is not None
    assert isinstance(result.preproc_report, PreprocessReport)
    assert result.preproc_report.output_data is not None
    assert result.preproc_report.output_data != data
    assert result.preproc_report.capture_source == "PHOTO"
    assert "sharpen" in result.preproc_report.applied


async def test_pipeline_blur_rejected_carries_preproc_report(settings: Settings) -> None:
    img = Image.new("RGB", (100, 100), "gray")
    data = _image_bytes(img)
    result = await run_pipeline(
        data,
        "image/png",
        "PHOTO",
        ocr_provider=_ocr_stub(""),
        llm_client=_FakeLLMClient(_llm_payload()),
        settings=settings,
    )
    assert result.error == "re-upload a clearer image"
    assert result.document is None
    assert result.validation is None
    assert result.preproc_report is not None
    assert result.preproc_report.blur_rejected is True
    assert result.preproc_report.capture_source == "PHOTO"


async def test_pipeline_empty_ocr_fails(settings: Settings) -> None:
    img = Image.new("RGB", (400, 200), "white")
    data = _image_bytes(img)

    def empty_ocr(_image: Image.Image) -> str:
        raise EmptyOCRError("no text extracted from image")

    result = await run_pipeline(
        data,
        "image/png",
        "PDF_SCAN",
        ocr_provider=empty_ocr,
        llm_client=_FakeLLMClient(_llm_payload()),
        settings=settings,
    )
    assert result.error == "no text extracted from image"


async def test_pipeline_llm_error_fails(settings: Settings) -> None:
    img = Image.new("RGB", (400, 200), "white")
    data = _image_bytes(img)

    class BadLLM(LLMClient):
        async def extract(self, ocr_text: str) -> dict[str, Any]:
            raise LLMExtractionError("model unreachable")

    result = await run_pipeline(
        data,
        "image/png",
        "PDF_SCAN",
        ocr_provider=_ocr_stub("some text"),
        llm_client=BadLLM(),
        settings=settings,
    )
    assert result.error is not None
    assert "LLM extraction failed" in result.error


async def test_pipeline_whatsapp_stronger_blur_threshold(settings: Settings) -> None:
    # A small pure-white image is extremely blurry; even with sharpening it
    # stays below a high WhatsApp threshold.
    settings.extraction_blur_threshold_photo = 500.0
    settings.extraction_blur_threshold_whatsapp = 1000.0
    img = Image.new("RGB", (100, 100), "white")
    data = _image_bytes(img)
    result = await run_pipeline(
        data,
        "image/png",
        "WHATSAPP",
        ocr_provider=_ocr_stub(""),
        llm_client=_FakeLLMClient(_llm_payload()),
        settings=settings,
    )
    assert result.error == "re-upload a clearer image"


async def test_pipeline_capture_source_preserved(settings: Settings) -> None:
    # Use a noisy image so blur gate does not reject, since this test is about
    # capture_source preservation, not blur.
    import numpy as np

    arr = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    data = _image_bytes(img)
    result = await run_pipeline(
        data,
        "image/png",
        "WHATSAPP",
        doc_id="W1",
        ocr_provider=_ocr_stub("ocr"),
        llm_client=_FakeLLMClient(_llm_payload()),
        settings=settings,
    )
    assert result.error is None
    assert result.document is not None
    assert result.document.capture_source == CaptureSource.WHATSAPP
    assert result.document.doc_id == "W1"


async def test_pipeline_applies_registration_pan(settings: Settings) -> None:
    pan = make_pan()
    img = Image.new("RGB", (400, 200), "white")
    data = _image_bytes(img)
    result = await run_pipeline(
        data,
        "image/png",
        "PDF_SCAN",
        ocr_provider=_ocr_stub("ocr"),
        llm_client=_FakeLLMClient(
            _llm_payload(supplier_gstin=make_gstin(pan=make_pan(), state_code="29"))
        ),
        settings=settings,
        registration_pan=pan,
    )
    assert result.validation is not None
    assert "PAN_CONSISTENCY" in {f.rule for f in result.validation.flags}


async def test_pipeline_duplicate_invoice(settings: Settings) -> None:
    img = Image.new("RGB", (400, 200), "white")
    data = _image_bytes(img)
    result = await run_pipeline(
        data,
        "image/png",
        "PDF_SCAN",
        ocr_provider=_ocr_stub("ocr"),
        llm_client=_FakeLLMClient(_llm_payload(invoice_no="INV-2025-0042")),
        settings=settings,
        existing_invoice_nos={"INV-2025-0042"},
    )
    assert result.validation is not None
    assert "DUPLICATE_INVOICE" in {f.rule for f in result.validation.flags}
