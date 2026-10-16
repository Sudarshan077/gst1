"""Heuristic regex-based extraction fallback for offline dev/test runs."""

from __future__ import annotations

import re
from typing import Any

from app.extraction.models import (
    CaptureSource,
    ExtractedDocument,
    ExtractedFields,
    ExtractedLine,
    FieldConfidence,
)

GSTIN_RE = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b")
INV_NO_RE = re.compile(
    r"(?:Invoice\s*No|Inv\s*No|Invoice\s*#|Bill\s*No|Invoice)\s*[:#\-]?\s*([A-Za-z0-9\-_/]+)",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"(?:Date|Invoice\s*Date|Dated)\s*[:#\-]?\s*(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(
    r"(?:Total|Grand\s*Total|Bill\s*Total|Total\s*Value|Total\s*Amount)\s*[:#\-INR₹]*\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
TAXABLE_RE = re.compile(
    r"(?:Taxable\s*Value|Taxable\s*Amount|Taxable)\s*[:#\-INR₹]*\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
CGST_RE = re.compile(
    r"(?:CGST|Central\s*Tax)\s*(?:\(?\d+%\)?)?\s*[:#\-INR₹]*\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
SGST_RE = re.compile(
    r"(?:SGST|State\s*Tax)\s*(?:\(?\d+%\)?)?\s*[:#\-INR₹]*\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
IGST_RE = re.compile(
    r"(?:IGST|Integrated\s*Tax)\s*(?:\(?\d+%\)?)?\s*[:#\-INR₹]*\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)


def _to_paise(val_str: str) -> int:
    clean = val_str.replace(",", "").strip()
    try:
        return int(round(float(clean) * 100))
    except ValueError:
        return 0


def extract_from_text_heuristic(
    ocr_text: str,
    doc_id: str | None = None,
    source: str = "PDF_SCAN",
) -> ExtractedDocument | None:
    """Extract standard Indian GST invoice fields using pattern matching."""
    if not ocr_text or len(ocr_text.strip()) < 10:
        return None

    # 1. GSTINs
    gstins = GSTIN_RE.findall(ocr_text)
    supplier_gstin = gstins[0] if len(gstins) > 0 else None
    buyer_gstin = gstins[1] if len(gstins) > 1 else None

    # 2. Invoice number
    inv_match = INV_NO_RE.search(ocr_text)
    invoice_no = inv_match.group(1).strip() if inv_match else None
    if not invoice_no and doc_id:
        invoice_no = f"INV-{doc_id[:8].upper()}"

    # 3. Invoice date
    date_match = DATE_RE.search(ocr_text)
    invoice_date = None
    if date_match:
        raw_d = date_match.group(1).replace("/", "-")
        parts = raw_d.split("-")
        if len(parts[0]) == 4:
            invoice_date = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        elif len(parts[2]) == 4:
            invoice_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

    # 4. Amounts
    tot_match = TOTAL_RE.search(ocr_text)
    total_value_paise = _to_paise(tot_match.group(1)) if tot_match else None

    tax_match = TAXABLE_RE.search(ocr_text)
    taxable_value_paise = _to_paise(tax_match.group(1)) if tax_match else None

    cgst_m = CGST_RE.search(ocr_text)
    cgst_paise = _to_paise(cgst_m.group(1)) if cgst_m else 0

    sgst_m = SGST_RE.search(ocr_text)
    sgst_paise = _to_paise(sgst_m.group(1)) if sgst_m else 0

    igst_m = IGST_RE.search(ocr_text)
    igst_paise = _to_paise(igst_m.group(1)) if igst_m else 0

    if total_value_paise and not taxable_value_paise:
        if cgst_paise + sgst_paise + igst_paise > 0:
            taxable_value_paise = total_value_paise - (cgst_paise + sgst_paise + igst_paise)
        else:
            taxable_value_paise = total_value_paise

    state_code = supplier_gstin[:2] if supplier_gstin else "27"
    is_inter = (buyer_gstin[:2] != state_code) if (buyer_gstin and supplier_gstin) else False

    fields = ExtractedFields(
        supplier_gstin=supplier_gstin,
        buyer_gstin=buyer_gstin,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        place_of_supply=state_code,
        is_inter_state=is_inter,
        rchrg=False,
        inv_typ="R",
        taxable_value_paise=taxable_value_paise,
        total_value_paise=total_value_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        igst_paise=igst_paise,
        cess_paise=0,
    )

    lines = []
    if taxable_value_paise:
        lines.append(
            ExtractedLine(
                hsn_sac="998313",
                desc="Item / Services",
                uqc="NOS",
                qty=1,
                unit_price_paise=taxable_value_paise,
                gst_rate=18.0 if (cgst_paise or igst_paise) else 0.0,
                taxable_value_paise=taxable_value_paise,
                cgst_paise=cgst_paise,
                sgst_paise=sgst_paise,
                igst_paise=igst_paise,
            )
        )

    confidence = FieldConfidence(
        supplier_gstin=0.95 if supplier_gstin else 0.0,
        buyer_gstin=0.90 if buyer_gstin else 0.0,
        invoice_no=0.95 if invoice_no else 0.0,
        invoice_date=0.90 if invoice_date else 0.0,
        total_value_paise=0.95 if total_value_paise else 0.0,
    )

    capture_val = CaptureSource.PDF_SCAN
    try:
        capture_val = CaptureSource(source)
    except Exception:
        pass

    return ExtractedDocument(
        doc_id=doc_id or invoice_no,
        capture_source=capture_val,
        fields=fields,
        lines=lines,
        confidence=confidence,
    )
