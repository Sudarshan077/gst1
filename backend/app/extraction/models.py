"""Pydantic models for extraction schema and validation.

Mirrors docs/EXTRACTION_SPEC.md §3 canonical schema with strict typing.
Money is always integer paise.
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaptureSource(enum.StrEnum):
    PDF_SCAN = "PDF_SCAN"
    DIGITAL = "DIGITAL"
    PHOTO = "PHOTO"
    WHATSAPP = "WHATSAPP"


class AutoConfirmStatus(enum.StrEnum):
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class FieldConfidence(BaseModel):
    supplier_gstin: float | None = None
    buyer_gstin: float | None = None
    invoice_no: float | None = None
    invoice_date: float | None = None
    place_of_supply: float | None = None
    is_inter_state: float | None = None
    rchrg: float | None = None
    inv_typ: float | None = None
    taxable_value_paise: float | None = None
    total_value_paise: float | None = None
    cgst_paise: float | None = None
    sgst_paise: float | None = None
    igst_paise: float | None = None
    cess_paise: float | None = None


class ExtractedFields(BaseModel):
    supplier_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_no: str | None = None
    invoice_date: str | None = None
    place_of_supply: str | None = None
    is_inter_state: bool | None = None
    rchrg: bool | None = None
    inv_typ: str | None = None
    taxable_value_paise: int | None = None
    total_value_paise: int | None = None
    cgst_paise: int | None = None
    sgst_paise: int | None = None
    igst_paise: int | None = None
    cess_paise: int | None = None

    supplier_name: str | None = None
    supplier_address: str | None = None
    buyer_name: str | None = None
    buyer_address: str | None = None

    model_config = ConfigDict(json_schema_extra={"required": []})


class ExtractedLine(BaseModel):
    hsn_sac: str | None = None
    desc: str | None = None
    uqc: str | None = None
    qty: int | None = None
    unit_price_paise: int | None = None
    gst_rate: float | None = None
    taxable_value_paise: int | None = None
    cgst_paise: int | None = None
    sgst_paise: int | None = None
    igst_paise: int | None = None


class ExtractedDocument(BaseModel):
    doc_id: str | None = None
    capture_source: CaptureSource
    fields: ExtractedFields = Field(default_factory=ExtractedFields)
    lines: list[ExtractedLine] = Field(default_factory=list)
    confidence: FieldConfidence = Field(default_factory=FieldConfidence)

    @field_validator("capture_source", mode="before")
    @classmethod
    def _coerce_capture_source(cls, v: Any) -> CaptureSource:
        if isinstance(v, CaptureSource):
            return v
        return CaptureSource(str(v).upper())


class ValidationFlag(BaseModel):
    rule: str
    severity: str  # "FLAG" | "AUTO_CORRECT" | "BLOCK" | "SUGGEST"
    field: str | None = None
    message: str


class ValidationResult(BaseModel):
    document: ExtractedDocument
    flags: list[ValidationFlag]
    auto_corrected: dict[str, Any]
    derived: dict[str, Any]
    auto_confirm: AutoConfirmStatus
    confidence_avg: float | None = None


class ExtractionResult(BaseModel):
    document: ExtractedDocument | None = None
    validation: ValidationResult | None = None
    ocr_text: str | None = None
    llm_model: str | None = None
    llm_tokens_in: int | None = None
    llm_tokens_out: int | None = None
    preproc_report: Any | None = None
    error: str | None = None
