"""Audit logger wrapper for linking and core operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import audit


async def log_audit_event(
    session: AsyncSession,
    action: str,
    entity_id: uuid.UUID | str | None = None,
    *,
    entity: str = "ca_client_links",
    actor_user_id: uuid.UUID | None = None,
    ca_firm_id: uuid.UUID | None = None,
    business_id: uuid.UUID | None = None,
    payload_diff: dict[str, Any] | None = None,
) -> None:
    await audit(
        session,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_user_id=actor_user_id,
        ca_firm_id=ca_firm_id,
        business_id=business_id,
        payload_diff=payload_diff,
    )
