"""Extraction pipeline: preprocess → OCR → LLM → validate.

Surface API:
    run_pipeline(document_bytes, mime_type, capture_source) -> ExtractedDocument
    validate_extraction(doc) -> ValidationResult
"""

from __future__ import annotations

from app.extraction.models import (
    AutoConfirmStatus,
    CaptureSource,
    ExtractedDocument,
    ExtractedLine,
    ExtractionResult,
    FieldConfidence,
    ValidationFlag,
    ValidationResult,
)
from app.extraction.pipeline import run_pipeline
from app.extraction.preprocess import PreprocessReport
from app.extraction.validate import validate_extraction

__all__ = [
    "AutoConfirmStatus",
    "CaptureSource",
    "ExtractedDocument",
    "ExtractedLine",
    "ExtractionResult",
    "FieldConfidence",
    "PreprocessReport",
    "run_pipeline",
    "validate_extraction",
    "ValidationFlag",
    "ValidationResult",
]
