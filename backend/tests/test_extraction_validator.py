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


# --------------------------------------------------------------------------
# Phase 9 task 9.5 — advisory WARN-tier rules
# --------------------------------------------------------------------------


def _warn_flags(result: Any) -> list[Any]:
    return [f for f in result.flags if f.severity == "WARN"]


def test_stale_invoice_date_warn_when_older_than_30d(base_doc: ExtractedDocument) -> None:
    """Invoice >30 days before the period end → STALE_INVOICE_DATE (WARN)."""
    base_doc.fields.invoice_date = "2025-03-01"
    result = validate_extraction(base_doc, period_fp="052025")  # period end 31 May
    stale = [f for f in _warn_flags(result) if f.rule == "STALE_INVOICE_DATE"]
    assert len(stale) == 1
    assert stale[0].field == "invoice_date"
    assert stale[0].severity == "WARN"
    # Advisory only: never a BLOCK, never an auto-correct.
    assert not any(f.severity == "BLOCK" for f in result.flags)
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW


def test_stale_invoice_date_boundary_is_exclusive(base_doc: ExtractedDocument) -> None:
    """Exactly 30 days before period end is fine; 31 days is stale."""
    # 2025-05-31 period end; 30 days back == 2025-05-01 (not stale).
    base_doc.fields.invoice_date = "2025-05-01"
    result = validate_extraction(base_doc, period_fp="052025")
    assert "STALE_INVOICE_DATE" not in _flag_codes(result)

    # 2025-04-30 is 31 days before 2025-05-31 (stale).
    base_doc.fields.invoice_date = "2025-04-30"
    result = validate_extraction(base_doc, period_fp="052025")
    assert "STALE_INVOICE_DATE" in _flag_codes(result)


def test_stale_invoice_date_needs_period_and_valid_dates(base_doc: ExtractedDocument) -> None:
    """No period, malformed invoice date, or malformed fp → no advisory."""
    base_doc.fields.invoice_date = "2020-01-01"
    assert "STALE_INVOICE_DATE" not in _flag_codes(validate_extraction(base_doc))
    assert "STALE_INVOICE_DATE" not in _flag_codes(
        validate_extraction(base_doc, period_fp="132026")  # month 13 is invalid
    )
    base_doc.fields.invoice_date = "not-a-date"
    assert "STALE_INVOICE_DATE" not in _flag_codes(
        validate_extraction(base_doc, period_fp="052025")
    )


def test_short_hsn_warn_below_six_digits(base_doc: ExtractedDocument) -> None:
    """HSN/SAC < 6 digits (or blank) → SHORT_HSN (WARN); ≥ 6 digits is fine."""
    base_doc.lines = [
        ExtractedLine(
            hsn_sac="9999", desc="Short", uqc="NOS", qty=1, gst_rate=0.0,
            taxable_value_paise=1500000,
        )
    ]
    result = validate_extraction(base_doc, period_fp="052025")
    short = [f for f in _warn_flags(result) if f.rule == "SHORT_HSN"]
    assert len(short) == 1
    assert short[0].severity == "WARN"
    assert not any(f.severity == "BLOCK" for f in result.flags)

    # A valid 8-digit HSN must not raise the advisory.
    base_doc.lines = [
        ExtractedLine(
            hsn_sac="73269099", desc="Bracket", uqc="NOS", qty=1, gst_rate=0.0,
            taxable_value_paise=1500000,
        )
    ]
    result = validate_extraction(base_doc, period_fp="052025")
    assert "SHORT_HSN" not in _flag_codes(result)


def test_short_hsn_warn_missing_code(base_doc: ExtractedDocument) -> None:
    """A blank/None HSN is also below the 6-digit floor → SHORT_HSN (WARN)."""
    base_doc.lines = [
        ExtractedLine(desc="No code", taxable_value_paise=1500000, gst_rate=0.0)
    ]
    result = validate_extraction(base_doc, period_fp="052025")
    assert "SHORT_HSN" in _flag_codes(result)


def test_warn_flags_do_not_block_and_do_not_auto_confirm(base_doc: ExtractedDocument) -> None:
    """WARN-tier findings keep the doc in review but add no BLOCK."""
    base_doc.fields.invoice_date = "2025-03-01"
    base_doc.lines = [ExtractedLine(desc="x", hsn_sac="12", taxable_value_paise=100, gst_rate=0.0)]
    result = validate_extraction(base_doc, period_fp="052025")
    assert {"STALE_INVOICE_DATE", "SHORT_HSN"} <= _flag_codes(result)
    severities = {f.severity for f in result.flags}
    assert "WARN" in severities
    assert "BLOCK" not in severities
    assert result.auto_confirm == AutoConfirmStatus.NEEDS_REVIEW
