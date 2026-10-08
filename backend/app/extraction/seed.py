"""Deterministic, local-only extraction seed for dev/test E2E.

Provides a fake OCR provider and fake LLM client that return a synthetically
valid extracted invoice. This lets the upload-to-output happy path run without
hitting external OCR/LLM services. Only the dev-mode extraction trigger uses
these helpers.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.extraction.llm import LLMClient
from app.extraction.models import (
    CaptureSource,
    ExtractedDocument,
    ExtractedFields,
    ExtractedLine,
    FieldConfidence,
)


def _seed_ocr_text(
    supplier_gstin: str,
    buyer_gstin: str,
    invoice_no: str,
    invoice_date: str,
) -> str:
    return (
        f"M/s Happy Path Co\n"
        f"GSTIN: {supplier_gstin}\n"
        f"Invoice No: {invoice_no}\n"
        f"Date: {invoice_date}\n"
        f"Buyer: Test Buyer\n"
        f"Buyer GSTIN: {buyer_gstin}\n"
        f"Place of Supply: {supplier_gstin[:2]}\n"
        f"Taxable: 1,000.00\n"
        f"CGST 9%: 90.00\n"
        f"SGST 9%: 90.00\n"
        f"Total: 1,180.00"
    )


def seed_ocr_provider(image: Image.Image) -> str:
    """Return a fixed OCR string; the real content comes from the LLM seed."""
    return "happy path seed OCR"


def _build_seed_document(gstin: str, invoice_no: str, invoice_date: str) -> ExtractedDocument:
    from app.core.gstin import make_gstin

    state_code = gstin[:2]
    # Intra-state B2B sale from the registered GSTIN to a valid buyer in the
    # same state — a checksum-valid GSTIN, never a hand-typed literal.
    seed_buyer = make_gstin(state_code=state_code)
    return ExtractedDocument(
        doc_id=invoice_no,
        capture_source=CaptureSource.PDF_SCAN,
        fields=ExtractedFields(
            supplier_gstin=gstin,
            buyer_gstin=seed_buyer,
            invoice_no=invoice_no,
            invoice_date=invoice_date,
            place_of_supply=state_code,
            is_inter_state=False,
            rchrg=False,
            inv_typ="R",
            taxable_value_paise=100_000,
            total_value_paise=118_000,
            cgst_paise=9_000,
            sgst_paise=9_000,
            igst_paise=0,
            cess_paise=0,
        ),
        lines=[
            ExtractedLine(
                hsn_sac="73269099",
                desc="Seed item",
                uqc="NOS",
                qty=1,
                unit_price_paise=100_000,
                gst_rate=18.0,
                taxable_value_paise=100_000,
                cgst_paise=9_000,
                sgst_paise=9_000,
                igst_paise=0,
            )
        ],
        confidence=FieldConfidence(
            supplier_gstin=0.98,
            buyer_gstin=0.98,
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
        ),
    )


class SeedLLMClient(LLMClient):
    """LLM client that returns a deterministic, clean extracted document."""

    def __init__(self, gstin: str, invoice_no: str, invoice_date: str) -> None:
        # Do not call LLMClient.__init__; we don't need real settings.
        self.gstin = gstin
        self.invoice_no = invoice_no
        self.invoice_date = invoice_date

    async def extract(self, ocr_text: str) -> dict[str, Any]:
        doc = _build_seed_document(self.gstin, self.invoice_no, self.invoice_date)
        data = doc.model_dump(mode="json")
        data["_llm_meta"] = {"model": "seed", "tokens_in": 0, "tokens_out": 0}
        return data

    def parse_document(self, raw: dict[str, Any]) -> ExtractedDocument:
        return ExtractedDocument.model_validate(raw)


def auto_invoice_no(doc_id: str) -> str:
    """Short deterministic invoice number derived from a document UUID."""
    return f"SEED-{doc_id[:8].upper()}"
