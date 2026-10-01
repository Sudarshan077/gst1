"""Pydantic schemas for CA-Client Linking and Consent (API_SPECIFICATION §3-4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FirmRequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_gstin: str | None = None
    gstin: str | None = None

    def get_gstin(self) -> str:
        val = self.client_gstin or self.gstin
        if not val:
            raise ValueError("gstin is required")
        return val


class FirmRequestOut(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str
    ca_firm_id: str
    business_id: str
    status: str
    requested_at: datetime | str | None = None


class InviteCodeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    business_id: str


class InviteCodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    invite_code: str
    expires_at: datetime | str | None = None
    id: str | None = None


class RedeemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invite_code: str


class RedeemOut(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str
    ca_firm_id: str
    business_id: str
    status: str
    consent_record_id: str | None = None


class ConsentAcceptIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    consent_text_version: str = "v1.0"


class ConsentAcceptOut(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str
    status: str
    consent_record_id: str | None = None
    consent_text_version: str = "v1.0"


class ConsentRevokeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str | None = None


class ConsentRevokeOut(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str
    status: str
    revoked_at: datetime | str | None = None
