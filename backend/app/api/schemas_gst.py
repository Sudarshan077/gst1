"""Pydantic schemas for /gst-accounts (task 0.6, v4 GSTIN-first)."""

from __future__ import annotations

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

    email: str = Field(min_length=3, max_length=255)
    role: str = Field(pattern="^(ADMIN|FILER|VIEWER)$")
