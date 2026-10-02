"""core schema: users, gst_accounts, user_gst_access, audit_logs.

Table shapes follow TECHNICAL_ARCHITECTURE.md §3 (v4.0 unified GSTIN-first) verbatim.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from app.db.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

CORE_SCHEMA = "core"


class AccessRole(enum.StrEnum):
    """Role of a user on a GSTIN."""

    ADMIN = "ADMIN"
    FILER = "FILER"
    VIEWER = "VIEWER"


class FilingScheme(enum.StrEnum):
    """Filing scheme of a GST registration."""

    REGULAR_MONTHLY = "REGULAR_MONTHLY"
    QRMP = "QRMP"
    COMPOSITION = "COMPOSITION"


class User(Base):
    """Person identity; email/mobile credential."""

    __tablename__ = "users"
    __table_args__ = {"schema": CORE_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    mobile: Mapped[str | None] = mapped_column(String(15), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    totp_secret: Mapped[str | None] = mapped_column(String(255))
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    gst_access: Mapped[list[UserGstAccess]] = relationship(back_populates="user")


class GstAccount(Base):
    """Primary entity = GSTIN. Every filing object, document, and invoice hangs
    off a GSTIN directly."""

    __tablename__ = "gst_accounts"
    __table_args__ = {"schema": CORE_SCHEMA}

    gstin: Mapped[str] = mapped_column(String(15), primary_key=True)
    pan: Mapped[str] = mapped_column(String(10), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(255))
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    filing_scheme: Mapped[FilingScheme] = mapped_column(
        Enum(FilingScheme, name="filing_scheme", schema=CORE_SCHEMA),
        nullable=False,
        default=FilingScheme.REGULAR_MONTHLY,
    )
    irn_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aato_latest_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    registered_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user_access: Mapped[list[UserGstAccess]] = relationship(back_populates="gst_account")


class UserGstAccess(Base):
    """Links users to GSTINs they can operate on."""

    __tablename__ = "user_gst_access"
    __table_args__ = (
        UniqueConstraint("user_id", "gstin", name="uq_user_gst_access_user_gstin"),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey(f"{CORE_SCHEMA}.users.id"), nullable=False
    )
    gstin: Mapped[str] = mapped_column(
        String(15), ForeignKey(f"{CORE_SCHEMA}.gst_accounts.gstin"), nullable=False
    )
    role: Mapped[AccessRole] = mapped_column(
        Enum(AccessRole, name="access_role", schema=CORE_SCHEMA), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="gst_access")
    gst_account: Mapped[GstAccount] = relationship(back_populates="user_access")


class AuditLog(Base):
    """Every data access logged; gstin replaces business_id/ca_firm_id."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity", "entity_id"),
        Index("ix_audit_logs_at", "at"),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey(f"{CORE_SCHEMA}.users.id")
    )
    gstin: Mapped[str | None] = mapped_column(
        String(15), ForeignKey(f"{CORE_SCHEMA}.gst_accounts.gstin")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload_diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
