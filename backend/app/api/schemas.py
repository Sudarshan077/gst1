"""Pydantic response/request models for /auth (API_SPECIFICATION.md §1 shapes)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OtpRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=5, max_length=255)
    purpose: str = Field(pattern="^(LOGIN|REGISTER)$")  # noqa: S105


class OtpRequestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp_sent: bool
    dev_otp: str | None = None


class OtpVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=5, max_length=255)
    otp: str = Field(min_length=6, max_length=6)


class PasswordLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Single user identity returned by /auth/* routes."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    email: str
    full_name: str
    totp_enabled: bool


class TokenPairOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: UserOut | None = None
    access_token: str
    refresh_token: str


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None


class RefreshOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str


class StepUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp: str = Field(min_length=6, max_length=6)


class StepUpOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stepup_token: str


class TotpSetupOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str
    qr_uri: str


class TotpVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=6)


class TotpEnabledOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class GstinRefOut(BaseModel):
    """One GSTIN the user can operate on, with their role on it."""

    model_config = ConfigDict(extra="forbid")

    gstin: str
    role: str
    legal_name: str


class MeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user: UserOut
    gst_accounts: list[GstinRefOut] = []


class MeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool = True
    data: MeOut


class ProfilePatchIn(BaseModel):
    """PATCH /me/profile body — full_name ONLY (PHASE8 8.1).

    extra="forbid" makes an {email: ...} (or any other field) a 422 at the
    validation layer — email is the login credential and read-only, never
    silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=255)


class ProfileEnvelope(BaseModel):
    """GET/PATCH /me/profile response — same UserDto shape as /auth/me."""

    model_config = ConfigDict(extra="forbid")
    success: bool = True
    data: UserOut


class EnvelopeError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class EnvelopeErrorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = False
    error: EnvelopeError


class EnvelopeDataOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = True
    data: dict[str, object] | list[object] | None = None


class DraftFieldUpdateIn(BaseModel):
    """Partial update of extracted fields in the review UI."""

    model_config = ConfigDict(extra="forbid")

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


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
