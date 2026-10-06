"""DPDP Act 2023 data-principal request registry (SECURITY_AND_ACCESS.md §4).

Stored inside the core schema so foreign keys to users/gst_accounts are
schema-local and retention policy is enforced alongside the audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.db.base import Base as GstBase
from sqlalchemy import JSON, Boolean, DateTime, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

CORE_SCHEMA = "core"


class DPDPRequestType(StrEnum):
    EXPORT = "EXPORT"
    ERASURE = "ERASURE"


class DPDPRequestStatus(StrEnum):
    PENDING = "PENDING"
    SLA_QUEUED = "SLA_QUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DPDPRequest(GstBase):
    """One row per data-principal request: export or erasure."""

    __tablename__ = "dpdp_requests"
    __table_args__ = {"schema": CORE_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), nullable=False
    )
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    request_type: Mapped[DPDPRequestType] = mapped_column(
        SAEnum(DPDPRequestType, name="dpdp_request_type", schema=CORE_SCHEMA),
        nullable=False,
    )
    status: Mapped[DPDPRequestStatus] = mapped_column(
        SAEnum(
            DPDPRequestStatus,
            name="dpdp_request_status",
            schema=CORE_SCHEMA,
        ),
        nullable=False,
        default=DPDPRequestStatus.PENDING,
    )
    retention_carve_out_applied: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    sla_due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
