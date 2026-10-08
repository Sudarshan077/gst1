"""Returns generate pipeline: one payload per return, rendered twice.

Task 8.4. The single-source-of-truth loader (PHASE8_PRODUCT_COMPLETENESS.md
§3.8.4): every consumer — the JSON exports, the .xlsx exports, the HSN
summary, POST /returns/generate and GET /returns/validation — builds ONE
payload per return via ``load_return_payload`` and renders it. JSON and
Excel can therefore never disagree.

Money is integer paise everywhere in this module; rupee conversion happens
in the xlsx renderer only (at render, never stored, never returned).

Loaders:
  - GSTR-1  : SALES invoices with status CONFIRMED/LOCKED, plus CONFIRMED
              notes (CDNR/CDNUR). GSTR-1 is an outward-supplies statement —
              purchase invoices never enter it (they feed 3B ITC instead).
  - GSTR-3B : CONFIRMED/LOCKED invoices of BOTH directions (the ITC tables
              consume purchases).
"""

from __future__ import annotations

from typing import Any

from app.api.errors import ServiceError
from app.db.models.gst import (
    CreditDebitNote,
    Invoice,
    InvoiceDirection,
    InvoiceStatus,
    NoteStatus,
)
from app.services.returns.gstr1 import (
    build_gstr1_from_invoices,
    validate_gstr1_payload,
)
from app.services.returns.gstr3b import (
    build_gstr3b_from_invoices,
    validate_gstr3b_payload,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

RETURN_FORMS = ("gstr1", "gstr3b")

_LOADABLE_STATUSES = (InvoiceStatus.CONFIRMED, InvoiceStatus.LOCKED)


async def _load_invoices(
    session: AsyncSession, gstin: str, fp: str, *, outward_only: bool
) -> list[Invoice]:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.lines))
        .where(
            Invoice.gstin == gstin,
            Invoice.fp == fp,
            Invoice.status.in_(_LOADABLE_STATUSES),
        )
    )
    if outward_only:
        stmt = stmt.where(Invoice.direction == InvoiceDirection.SALES)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _load_notes(session: AsyncSession, gstin: str, fp: str) -> list[CreditDebitNote]:
    stmt = select(CreditDebitNote).where(
        CreditDebitNote.gstin == gstin,
        CreditDebitNote.fp == fp,
        CreditDebitNote.status == NoteStatus.CONFIRMED,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def load_gstr1_payload(
    session: AsyncSession, gstin: str, fp: str
) -> dict[str, Any]:
    """Build + validate the GSTR-1 payload for one (gstin, fp)."""
    invoices = await _load_invoices(session, gstin, fp, outward_only=True)
    notes = await _load_notes(session, gstin, fp)
    payload = build_gstr1_from_invoices(gstin, fp, invoices, notes=notes)
    ok, err = validate_gstr1_payload(payload)
    if not ok:
        raise ServiceError(f"generated GSTR-1 invalid: {err}", 500, "INTERNAL_ERROR")
    return payload


async def load_gstr3b_payload(
    session: AsyncSession, gstin: str, fp: str
) -> dict[str, Any]:
    """Build + validate the GSTR-3B payload for one (gstin, fp)."""
    invoices = await _load_invoices(session, gstin, fp, outward_only=False)
    payload = build_gstr3b_from_invoices(gstin, fp, invoices)
    ok, err = validate_gstr3b_payload(payload)
    if not ok:
        raise ServiceError(f"generated GSTR-3B invalid: {err}", 500, "INTERNAL_ERROR")
    return payload


async def load_return_payload(
    session: AsyncSession, gstin: str, fp: str, form: str
) -> dict[str, Any]:
    """Dispatch loader by return form name ('gstr1' | 'gstr3b')."""
    if form == "gstr1":
        return await load_gstr1_payload(session, gstin, fp)
    if form == "gstr3b":
        return await load_gstr3b_payload(session, gstin, fp)
    raise ServiceError(f"unsupported return form: {form}", 422, "VALIDATION_ERROR")


# --------------------------------------------------------------- HSN summary


def build_hsn_summary_from_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate the GSTR-1 payload's B2B/CDNR/CDNUR line items by (HSN, rate).

    Reconciles to GSTR-1 by construction: the only money source is the same
    payload the JSON/xlsx exporters render. A line with no hsn_sac falls
    into the blank-HSN bucket ('' key) so totals always reconcile.
    """
    buckets: dict[tuple[str, float], dict[str, Any]] = {}

    def _add(hsn: str | None, item: dict[str, Any]) -> None:
        key = (hsn or "", float(item.get("rt") or 0.0))
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "hsn_sac": hsn or "",
                "rt": item.get("rt", 0.0),
                "txval_paise": 0,
                "iamt_paise": 0,
                "camt_paise": 0,
                "samt_paise": 0,
                "csamt_paise": 0,
                "num_of_lines": 0,
            }
            buckets[key] = bucket
        bucket["txval_paise"] += int(item.get("txval_paise") or 0)
        bucket["iamt_paise"] += int(item.get("iamt_paise") or 0)
        bucket["camt_paise"] += int(item.get("camt_paise") or 0)
        bucket["samt_paise"] += int(item.get("samt_paise") or 0)
        bucket["csamt_paise"] += int(item.get("csamt_paise") or 0)
        bucket["num_of_lines"] += 1

    for entry in payload.get("b2b", []):
        for inv in entry.get("inv", []):
            for item in inv.get("itms", []):
                _add(item.get("hsn_sac"), item)
    for entry in payload.get("cdnr", []):
        for note in entry.get("nt", []):
            for item in note.get("itms", []):
                _add(item.get("hsn_sac"), item)
    for entry in payload.get("cdnur", []):
        for note in entry.get("nt", []):
            for item in note.get("itms", []):
                _add(item.get("hsn_sac"), item)

    return sorted(
        buckets.values(),
        key=lambda b: (b["hsn_sac"], b["rt"]),
    )


def hsn_summary_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Row-wise sums — the reconciliation target for tests and the UI footer."""
    return {
        "txval_paise": sum(r["txval_paise"] for r in rows),
        "iamt_paise": sum(r["iamt_paise"] for r in rows),
        "camt_paise": sum(r["camt_paise"] for r in rows),
        "samt_paise": sum(r["samt_paise"] for r in rows),
        "csamt_paise": sum(r["csamt_paise"] for r in rows),
    }
