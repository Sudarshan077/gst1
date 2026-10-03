from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, DateTime, String, Boolean, JSON, Enum as SAEnum, Uuid
from sqlalchemy.orm import DeclarativeBase

class DPDPBase(DeclarativeBase):
    pass

class DPDPRequestType(str, Enum):
    EXPORT = "EXPORT"
    ERASURE = "ERASURE"

class DPDPRequestStatus(str, Enum):
    PENDING = "PENDING"
    SLA_QUEUED = "SLA_QUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DPDPRequest(DPDPBase):
    __tablename__ = "dpdp_requests"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, nullable=False)
    gstin = Column(String, nullable=False)
    request_type = Column(SAEnum(DPDPRequestType), nullable=False)
    status = Column(SAEnum(DPDPRequestStatus), default=DPDPRequestStatus.PENDING)
    retention_carve_out_applied = Column(Boolean, default=False)
    sla_due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    payload = Column(JSON, nullable=True)
