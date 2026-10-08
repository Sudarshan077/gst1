"""Pydantic schemas for /gst-accounts (task 0.6, v4 GSTIN-first)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GstAccountCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gstin: str = Field(min_length=15, max_length=15)
    legal_name: str = Field(min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    registered_address: str | None = Field(default=None, max_length=1000)
    aato_minor: int | None = Field(default=None, ge=0, description="AATO in paise")
    filing_scheme: str | None = Field(
        default=None, pattern="^(REGULAR_MONTHLY|QRMP|COMPOSITION)$"
    )


class GstAccountPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    registered_address: str | None = Field(default=None, max_length=1000)
    aato_minor: int | None = Field(default=None, ge=0, description="AATO in paise")
    filing_scheme: str | None = Field(
        default=None, pattern="^(REGULAR_MONTHLY|QRMP|COMPOSITION)$"
    )


class GstAccountOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    gstin: str
    legal_name: str
    trade_name: str | None
    pan: str
    state_code: str
    filing_scheme: str
    irn_applicable: bool
    aato_latest_minor: int
    registered_address: str | None
    role: str
    created_at: str | None


class CollaboratorInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1)
    role: str = Field(min_length=1)


class CollaboratorUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)


class Gstr2bImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any]


class Gstr2bStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    gstin: str
    fp: str
    source: str
    downloaded_at: datetime


class ItcReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    purchase_invoice_id: uuid.UUID | None
    gstr2b_entry_id: uuid.UUID | None
    match_status: str
    confidence: float | None
    remarks: str | None


class MonthSummaryOut(BaseModel):
    """Month card data: doc counts, ledger totals, deadline, nil flag (API_SPEC §2)."""

    model_config = ConfigDict(extra="forbid")

    fp: str
    status: str
    gstr1_due_date: str | None = None
    gstr3b_due_date: str | None = None
    days_to_deadline: int | None = None
    doc_count: int
    confirmed_count: int
    review_count: int
    pending_count: int
    failed_count: int
    total_taxable_minor: int
    total_cgst_minor: int
    total_sgst_minor: int
    total_igst_minor: int
    total_cess_minor: int
    nil_eligible: bool = False
