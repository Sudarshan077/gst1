"""Validator implementing EXTRACTION_SPEC.md §6 rules.

Rules:
  - GSTIN format + mod-36 checksum (both parties)
  - PAN consistency (registration PAN == GSTIN[2:12])
  - Tax recompute: per-line cgst/sgt/igst from taxable * rate, HALF_UP per line,
    sum to invoice totals; auto-correct, flag if printed != recomputed > 1 INR
  - Supply type: intra (POS == supplier state) vs inter; compute from data
  - fp derivation from invoice_date (MMYYYY)
  - Place-of-supply code in valid state-code set
  - Duplicate invoice_no within (registration, fp)
  - rchrg/inv_typ inference from keywords
  - Negative amounts / zero-value lines flag
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.gstin import gstin_state_code, validate_gstin
from app.extraction.models import (
    AutoConfirmStatus,
    CaptureSource,
    ExtractedDocument,
    ExtractedFields,
    ValidationFlag,
    ValidationResult,
)

VALID_STATE_CODES: frozenset[str] = frozenset(
    f"{i:02d}" for i in range(1, 38)
) | {"97", "98", "99"}

MANDATORY_FIELDS: tuple[str, ...] = (
    "supplier_gstin",
    "buyer_gstin",
    "invoice_no",
    "invoice_date",
    "place_of_supply",
    "is_inter_state",
    "rchrg",
    "inv_typ",
    "taxable_value_paise",
    "total_value_paise",
    "cgst_paise",
    "sgst_paise",
    "igst_paise",
    "cess_paise",
)

AUTO_CONFIRM_CONFIDENCE: dict[CaptureSource, float] = {
    CaptureSource.PDF_SCAN: 0.90,
    CaptureSource.DIGITAL: 0.90,
    CaptureSource.PHOTO: 0.97,
    CaptureSource.WHATSAPP: 0.97,
}


class ValidatorError(Exception):
    """Validator internal error."""


def _paise(value: int | None) -> int:
    return int(value or 0)


def _derive_fp(invoice_date: str | None) -> str | None:
    """MMYYYY from "YYYY-MM-DD"."""
    if not invoice_date:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", invoice_date)
    if not m:
        return None
    return f"{m.group(2)}{m.group(1)}"


def _money_diff(a: int | None, b: int | None) -> int:
    return abs(_paise(a) - _paise(b))


def _recompute_tax(
    fields: ExtractedFields,
    lines: list[Any],
) -> tuple[ExtractedFields, dict[str, Any], bool]:
    """Return (corrected_fields, per_line_corrections, had_discrepancy).

    Algorithm: if lines have taxable_value + rate, recompute line tax HALF_UP,
    sum to invoice tax. Then set totals. Flag if printed totals differ by
    more than INR 1 (100 paise).
    """
    corrected = fields.model_copy(deep=True)
    corrections: dict[str, Any] = {}
    had_discrepancy = False

    supplier_state = None
    if fields.supplier_gstin:
        try:
            supplier_state = gstin_state_code(fields.supplier_gstin)
        except ValueError:
            pass

    is_inter = bool(fields.is_inter_state)
    place = fields.place_of_supply

    # --- per-line recompute -------------------------------------------------
    line_cgst = 0
    line_sgst = 0
    line_igst = 0
    line_taxable = 0
    trust_inter = is_inter or (supplier_state is not None and place and place != supplier_state)
    for line in lines:
        rate = float(line.gst_rate or 0)
        taxable = _paise(line.taxable_value_paise)
        line_taxable += taxable
        tax = int((Decimal(taxable) * Decimal(rate) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ))
        if trust_inter:
            line_igst += tax
        else:
            half = int((Decimal(tax) / Decimal(2)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            ))
            line_cgst += half
            line_sgst += tax - half  # adjust rounding penny if any

    # --- invoice-level recompute when lines exist ---------------------------
    if lines:
        if _money_diff(corrected.cgst_paise, line_cgst) > 100 or (
            corrected.cgst_paise is None and line_cgst != 0
        ):
            corrections["cgst_paise"] = {"printed": corrected.cgst_paise, "recomputed": line_cgst}
            corrected.cgst_paise = line_cgst
            had_discrepancy = True
        elif line_cgst == 0 and corrected.cgst_paise is None:
            corrected.cgst_paise = 0
        if _money_diff(corrected.sgst_paise, line_sgst) > 100 or (
            corrected.sgst_paise is None and line_sgst != 0
        ):
            corrections["sgst_paise"] = {"printed": corrected.sgst_paise, "recomputed": line_sgst}
            corrected.sgst_paise = line_sgst
            had_discrepancy = True
        elif line_sgst == 0 and corrected.sgst_paise is None:
            corrected.sgst_paise = 0
        if _money_diff(corrected.igst_paise, line_igst) > 100 or (
            corrected.igst_paise is None and line_igst != 0
        ):
            corrections["igst_paise"] = {"printed": corrected.igst_paise, "recomputed": line_igst}
            corrected.igst_paise = line_igst
            had_discrepancy = True
        elif line_igst == 0 and corrected.igst_paise is None:
            corrected.igst_paise = 0
        expected_total = (
            _paise(corrected.taxable_value_paise)
            + _paise(corrected.cgst_paise)
            + _paise(corrected.sgst_paise)
            + _paise(corrected.igst_paise)
            + _paise(corrected.cess_paise)
        )
        if _money_diff(corrected.total_value_paise, expected_total) > 100:
            corrections["total_value_paise"] = {
                "printed": corrected.total_value_paise,
                "recomputed": expected_total,
            }
            corrected.total_value_paise = expected_total
            had_discrepancy = True

    # --- fallback when no lines: still ensure total == taxable + taxes --------
    expected_total = (
        _paise(corrected.taxable_value_paise)
        + _paise(corrected.cgst_paise)
        + _paise(corrected.sgst_paise)
        + _paise(corrected.igst_paise)
        + _paise(corrected.cess_paise)
    )
    if _money_diff(corrected.total_value_paise, expected_total) > 100:
        corrections["total_value_paise"] = {
            "printed": corrected.total_value_paise,
            "recomputed": expected_total,
        }
        corrected.total_value_paise = expected_total
        had_discrepancy = True

    return corrected, corrections, had_discrepancy


def _infer_inv_typ(ocr_text: str) -> str | None:
    text = ocr_text.upper()
    if "SEZ" in text and "WITH PAYMENT" in text:
        return "SEWP"
    if "SEZ" in text:
        return "SEWOP"
    if "DEEMED EXPORT" in text or "DEEMEDEXPORT" in text:
        return "DE"
    return None


def _infer_rchrg(ocr_text: str) -> bool | None:
    text = ocr_text.upper()
    if "REVERSE CHARGE" in text or "RCM" in text or "REVERSECHARGE" in text:
        return True
    return None


def validate_extraction(
    doc: ExtractedDocument,
    *,
    registration_pan: str | None = None,
    ocr_text: str = "",
    existing_invoice_nos: set[str] | None = None,
) -> ValidationResult:
    """Run all EXTRACTION_SPEC §6 validation rules.

    Args:
        doc: extracted document (LLM output).
        registration_pan: business PAN for cross-check against supplier_gstin.
        ocr_text: raw OCR text used for rchrg/inv_typ keyword inference.
        existing_invoice_nos: set of invoice_no already in the period.
    """
    flags: list[ValidationFlag] = []
    fields = doc.fields

    # --- 1. GSTIN format + checksum -----------------------------------------
    for role, gstin in (("supplier", fields.supplier_gstin), ("buyer", fields.buyer_gstin)):
        if gstin is None:
            continue
        try:
            validate_gstin(gstin)
        except ValueError as exc:
            flags.append(ValidationFlag(
                rule="GSTIN_FORMAT" if "format" in str(exc).lower() else "GSTIN_CHECKSUM",
                severity="FLAG",
                field=f"{role}_gstin",
                message=f"{role}_gstin invalid: {exc}",
            ))

    # --- 2. PAN consistency (registration PAN must match a party on the doc) -
    if registration_pan:
        reg_pan = registration_pan.upper()
        pan_matched = False
        if fields.supplier_gstin and fields.supplier_gstin[2:12] == reg_pan:
            pan_matched = True
        if fields.buyer_gstin and fields.buyer_gstin[2:12] == reg_pan:
            pan_matched = True
        if not pan_matched:
            flags.append(ValidationFlag(
                rule="PAN_CONSISTENCY",
                severity="BLOCK",
                field="supplier_gstin,buyer_gstin",
                message="no party GSTIN PAN matches the registration PAN",
            ))

    # --- 3. Place of supply code valid -------------------------------------
    if fields.place_of_supply is not None and fields.place_of_supply not in VALID_STATE_CODES:
        flags.append(ValidationFlag(
            rule="POS_VALID",
            severity="FLAG",
            field="place_of_supply",
            message=f"place_of_supply {fields.place_of_supply} is not a valid state code",
        ))

    # --- 4. Derive supply type ---------------------------------------------
    derived_supply_type: str | None = None
    if fields.supplier_gstin and fields.place_of_supply:
        try:
            supplier_state = gstin_state_code(fields.supplier_gstin)
            derived_supply_type = "INTER" if supplier_state != fields.place_of_supply else "INTRA"
        except ValueError:
            flags.append(ValidationFlag(
                rule="SUPPLY_TYPE",
                severity="FLAG",
                field="is_inter_state",
                message="cannot compute supply_type: invalid supplier GSTIN",
            ))

    # --- 5. fp derivation ---------------------------------------------------
    derived_fp = _derive_fp(fields.invoice_date)

    # --- 6. Tax recompute / auto-correct -----------------------------------
    corrected, tax_corrections, tax_discrepancy = _recompute_tax(fields, doc.lines)
    if tax_discrepancy:
        for field, detail in tax_corrections.items():
            flags.append(ValidationFlag(
                rule="TAX_RECOMPUTE",
                severity="AUTO_CORRECT",
                field=field,
                message=(
                    f"{field} printed {detail['printed']} paise differs from "
                    f"recomputed {detail['recomputed']} paise; auto-corrected"
                ),
            ))

    # --- 7. Duplicate invoice_no --------------------------------------------
    if fields.invoice_no and existing_invoice_nos:
        if fields.invoice_no.strip().upper() in {
            n.strip().upper() for n in existing_invoice_nos
        }:
            flags.append(ValidationFlag(
                rule="DUPLICATE_INVOICE",
                severity="FLAG",
                field="invoice_no",
                message="duplicate invoice_no in this registration/filing period",
            ))

    # --- 8. rchrg / inv_typ inference suggestion ----------------------------
    inferred_inv_typ = _infer_inv_typ(ocr_text)
    if inferred_inv_typ and fields.inv_typ and inferred_inv_typ != fields.inv_typ.upper():
        flags.append(ValidationFlag(
            rule="INVTYP_INFERENCE",
            severity="SUGGEST",
            field="inv_typ",
            message=f"invoice keywords suggest inv_typ={inferred_inv_typ}",
        ))
    inferred_rchrg = _infer_rchrg(ocr_text)
    if inferred_rchrg is not None and fields.rchrg != inferred_rchrg:
        flags.append(ValidationFlag(
            rule="RCHRG_INFERENCE",
            severity="SUGGEST",
            field="rchrg",
            message=f"invoice keywords suggest rchrg={inferred_rchrg}",
        ))

    # --- 9. Negative / zero amounts -----------------------------------------
    for name in (
        "taxable_value_paise",
        "total_value_paise",
        "cgst_paise",
        "sgst_paise",
        "igst_paise",
        "cess_paise",
    ):
        value = getattr(corrected, name)
        if value is not None and value < 0:
            flags.append(ValidationFlag(
                rule="NEGATIVE_AMOUNT",
                severity="FLAG",
                field=name,
                message=f"{name} is negative",
            ))
    if corrected.taxable_value_paise is not None and corrected.taxable_value_paise == 0:
        flags.append(ValidationFlag(
            rule="ZERO_VALUE",
            severity="FLAG",
            field="taxable_value_paise",
            message="taxable value is zero",
        ))
    for line in doc.lines:
        if line.taxable_value_paise is not None and line.taxable_value_paise <= 0:
            flags.append(ValidationFlag(
                rule="ZERO_VALUE_LINE",
                severity="FLAG",
                field="lines",
                message="line taxable value is zero or negative",
            ))

    # --- auto-confirm decision ----------------------------------------------
    threshold = AUTO_CONFIRM_CONFIDENCE.get(doc.capture_source, 0.90)
    eligible = True
    conf = doc.confidence.model_dump()
    for field in MANDATORY_FIELDS:
        value = getattr(corrected, field)
        field_conf = conf.get(field)
        if field == "buyer_gstin" and value is None:
            continue  # B2C invoices legitimately have no buyer GSTIN
        if value is None:
            eligible = False
        elif field_conf is None or field_conf < threshold:
            eligible = False

    if any(f.severity == "BLOCK" for f in flags):
        auto_confirm = AutoConfirmStatus.NEEDS_REVIEW
    elif any(f.severity in {"FLAG", "AUTO_CORRECT", "SUGGEST"} for f in flags):
        auto_confirm = AutoConfirmStatus.NEEDS_REVIEW
    elif eligible:
        auto_confirm = AutoConfirmStatus.AUTO_CONFIRMED
    else:
        auto_confirm = AutoConfirmStatus.NEEDS_REVIEW

    derived = {
        "supply_type": derived_supply_type,
        "fp": derived_fp,
        "supplier_state": supplier_state if 'supplier_state' in locals() else None,
    }

    confidence_values = [v for v in conf.values() if v is not None]
    confidence_avg = sum(confidence_values) / len(confidence_values) if confidence_values else None

    corrected_doc = doc.model_copy(update={"fields": corrected}, deep=True)

    return ValidationResult(
        document=corrected_doc,
        flags=flags,
        auto_corrected=tax_corrections,
        derived=derived,
        auto_confirm=auto_confirm,
        confidence_avg=confidence_avg,
    )
