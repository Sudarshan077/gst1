"""Unit tests for extraction validator rules (EXTRACTION_SPEC.md §6)."""

from __future__ import annotations

from typing import Any

import pytest
from app.extraction.models import (
    AutoConfirmStatus,
    CaptureSource,
    ExtractedDocument,
    ExtractedFields,
    ExtractedLine,
    FieldConfidence,
)
from app.extraction.validate import validate_extraction

from tests.gstin_fixtures import make_gstin, make_pan


@pytest.fixture()
def valid_fields() -> ExtractedFields:
    return ExtractedFields(
        supplier_gstin=make_gstin(pan=make_pan(), state_code="27"),
        buyer_gstin=None,
        invoice_no="INV-2025-0042",
        invoice_date="2025-05-04",
        place_of_supply="27",
        is_inter_state=False,
        rchrg=False,
        inv_typ="R",
        taxable_value_paise=1500000,
        total_value_paise=1770000,
        cgst_paise=135000,
        sgst_paise=135000,
        igst_paise=0,
        cess_paise=0,
    )


@pytest.fixture()
def high_confidence() -> FieldConfidence:
    return FieldConfidence(
        supplier_gstin=0.99,
        invoice_no=0.99,
        invoice_date=0.99,
        place_of_supply=0.99,
        is_inter_state=0.99,
        rchrg=0.99,
        inv_typ=0.99,
        taxable_value_paise=0.99,
        total_value_paise=0.99,
        cgst_paise=0.99,
        sgst_paise=0.99,
        igst_paise=0.99,
        cess_paise=0.99,
    )


@pytest.fixture()
def base_doc(valid_fields: ExtractedFields, high_confidence: FieldConfidence) -> ExtractedDocument:
    return ExtractedDocument(
        doc_id="INV-0001",
        capture_source=CaptureSource.PDF_SCAN,
        fields=valid_fields,
        confidence=high_confidence,
    )


def _flag_codes(result: Any) -> set[str]:
    return {f.rule for f in result.flags}


def test_valid_pdf_scan_auto_confirms(base_doc: ExtractedDocument) -> None:
    result = validate_extraction(base_doc)
    assert result.auto_confirm == AutoConfirmStatus.AUTO_CONFIRMED
    assert result.derived["supply_type"] == "INTRA"
    assert result.derived["fp"] == "052025"
    assert not result.flags


def test_invalid_supplier_gstin_format_flagged(base_doc: ExtractedDocument) -> None:
    base_doc.fields.supplier_gstin = "27INVALID"
    base_doc.confidence.supplier_gstin = 0.99
    result = validate_extraction(base_doc)
    assert "GSTIN_FORMAT" in _flag_codes(result)
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW


def test_invalid_supplier_gstin_checksum_flagged(base_doc: ExtractedDocument) -> None:
    # structurally valid length but wrong check digit
    base_doc.fields.supplier_gstin = "27AABCU9603R1ZZ"
    base_doc.confidence.supplier_gstin = 0.99
    result = validate_extraction(base_doc)
    assert "GSTIN_CHECKSUM" in _flag_codes(result)


def test_pan_consistency_block(base_doc: ExtractedDocument) -> None:
    # registration PAN is different from supplier PAN embedded in GSTIN
    result = validate_extraction(base_doc, registration_pan="AAAAA0000A")
    assert "PAN_CONSISTENCY" in _flag_codes(result)
    assert any(f.severity == "BLOCK" for f in result.flags)
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW


def test_pan_consistency_buyer_match_ok(base_doc: ExtractedDocument) -> None:
    pan = make_pan()
    base_doc.fields.buyer_gstin = make_gstin(pan=pan, state_code="27")
    base_doc.confidence.buyer_gstin = 0.99
    result = validate_extraction(base_doc, registration_pan=pan)
    assert "PAN_CONSISTENCY" not in _flag_codes(result)


def test_invalid_place_of_supply_flagged(base_doc: ExtractedDocument) -> None:
    base_doc.fields.place_of_supply = "99"
    result = validate_extraction(base_doc)
    # 99 is valid (other territory)
    assert "POS_VALID" not in _flag_codes(result)

    base_doc.fields.place_of_supply = "55"
    result = validate_extraction(base_doc)
    assert "POS_VALID" in _flag_codes(result)


def test_supply_type_derived(base_doc: ExtractedDocument) -> None:
    base_doc.fields.place_of_supply = "29"
    result = validate_extraction(base_doc)
    assert result.derived["supply_type"] == "INTER"

    base_doc.fields.place_of_supply = "27"
    result = validate_extraction(base_doc)
    assert result.derived["supply_type"] == "INTRA"


def test_fp_derived(base_doc: ExtractedDocument) -> None:
    result = validate_extraction(base_doc)
    assert result.derived["fp"] == "052025"

    base_doc.fields.invoice_date = None
    result = validate_extraction(base_doc)
    assert result.derived["fp"] is None


def test_tax_recompute_auto_correct(base_doc: ExtractedDocument) -> None:
    base_doc.lines = [ExtractedLine(
        hsn_sac="73269099", desc="Bracket", uqc="NOS", qty=100,
        unit_price_paise=15000, gst_rate=18.0,
        taxable_value_paise=1500000,
    )]
    base_doc.fields.cgst_paise = 140000
    base_doc.fields.total_value_paise = 1775000
    result = validate_extraction(base_doc)
    assert "TAX_RECOMPUTE" in _flag_codes(result)
    assert result.document.fields.cgst_paise == 135000
    assert result.document.fields.total_value_paise == 1770000


def test_tax_recompute_from_lines(base_doc: ExtractedDocument) -> None:
    base_doc.lines = [ExtractedLine(
        hsn_sac="73269099", desc="Bracket", uqc="NOS", qty=100,
        unit_price_paise=15000, gst_rate=18.0,
        taxable_value_paise=1500000,
    )]
    base_doc.fields.cgst_paise = None
    base_doc.fields.sgst_paise = None
    base_doc.fields.igst_paise = None
    base_doc.fields.total_value_paise = 1770000
    result = validate_extraction(base_doc)
    assert result.document.fields.cgst_paise == 135000
    assert result.document.fields.sgst_paise == 135000
    assert result.document.fields.igst_paise == 0


def test_duplicate_invoice_flagged(base_doc: ExtractedDocument) -> None:
    result = validate_extraction(base_doc, existing_invoice_nos={"inv-2025-0042"})
    assert "DUPLICATE_INVOICE" in _flag_codes(result)


def test_rchrg_invtyp_inference_suggest(base_doc: ExtractedDocument) -> None:
    ocr = "Supplier: X\nInvoice: 1\nDate: 04/05/2025\nREVERSE CHARGE applicable"
    result = validate_extraction(base_doc, ocr_text=ocr)
    assert "RCHRG_INFERENCE" in _flag_codes(result)

    ocr = "Supply to SEZ unit without payment of tax"
    base_doc.fields.inv_typ = "R"
    result = validate_extraction(base_doc, ocr_text=ocr)
    assert "INVTYP_INFERENCE" in _flag_codes(result)


def test_negative_amounts_flagged(base_doc: ExtractedDocument) -> None:
    base_doc.fields.cgst_paise = -100
    result = validate_extraction(base_doc)
    assert "NEGATIVE_AMOUNT" in _flag_codes(result)


def test_zero_taxable_value_flagged(base_doc: ExtractedDocument) -> None:
    base_doc.fields.taxable_value_paise = 0
    result = validate_extraction(base_doc)
    assert "ZERO_VALUE" in _flag_codes(result)


def test_auto_confirm_thresholds(base_doc: ExtractedDocument) -> None:
    result = validate_extraction(base_doc)
    assert result.auto_confirm == AutoConfirmStatus.AUTO_CONFIRMED

    base_doc.capture_source = CaptureSource.PHOTO
    result = validate_extraction(base_doc)
    assert result.auto_confirm == AutoConfirmStatus.AUTO_CONFIRMED

    base_doc.confidence.invoice_no = 0.90
    result = validate_extraction(base_doc)
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW


def test_missing_mandatory_field_needs_review(base_doc: ExtractedDocument) -> None:
    base_doc.fields.invoice_no = None
    result = validate_extraction(base_doc)
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW
