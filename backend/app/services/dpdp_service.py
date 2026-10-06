"""DPDP service wiring — re-export the canonical implementation.

Keeps `app.services.dpdp_service` stable so routers import from a single place
while the heavy logic lives in `app.services.dpdp`.
"""

from __future__ import annotations

from app.services.dpdp import export_data, request_erasure

__all__ = ["export_data", "request_erasure"]

