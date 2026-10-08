"""Pre-filing validation for a (gstin, fp) — the "error catcher" (task 8.4).

Re-uses the shipped machinery, never a parallel rule set
(PHASE8_PRODUCT_COMPLETENESS.md §3.8.4 Rules):
  - payload builders + their self-validators (services/returns/gstr1.py,
    gstr3b.py) decide payload validity;
  - the mod-36 GSTIN validator (app/core/gstin.py) decides GSTIN validity;
  - the FilingPeriod row decides the filed-period conflict.

Findings are split into ``blocking`` (cannot file until fixed) and
``warnings`` (file-able but a human should look). Money is integer paise.
"""

from __future__ import annotations

from typing import Any

from app.api.errors import ServiceError
from app.core.gstin import validate_gstin
from app.db.models.gst import (
    CreditDebitNote,
    FilingPeriod,
    FilingStatus,
    Invoice,
    InvoiceDirection,
    InvoiceStatus,
    NoteStatus,
)
from app.services.returns.pipeline import (
    build_hsn_summary_from_payload,
    load_gstr1_payload,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def validate_period_for_filing(
    session: AsyncSession, gstin: str, fp: str
) -> dict[str, Any]:
    """Run the pre-filing checks and return ``{blocking: [...], warnings: [...]}``."""
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def _block(rule: str, message: str, **extra: Any) -> None:
        blocking.append({"rule": rule, "message": message, **extra})

    def _warn(rule: str, message: str, **extra: Any) -> None:
        warnings.append({"rule": rule, "message": message, **extra})

    # --- 1. filed-period conflict (originals are immutable post-filing) -----
    period = await session.get(FilingPeriod, (gstin, fp))
    if period is not None and period.status == FilingStatus.FILED:
        _block(
            "PERIOD_ALREADY_FILED",
            "This filing period is already FILED; file an amendment (GSTR-1A) "
            "instead of re-filing the original",
            filed_at=period.filed_at.isoformat() if period.filed_at else None,
        )

    # --- 2. payload builds cleanly (re-uses the builders + self-validators) --
    try:
        payload = await load_gstr1_payload(session, gstin, fp)
    except ServiceError as exc:
        _block("GSTR1_BUILD_FAILED", exc.message)
        return {"blocking": blocking, "warnings": warnings, "gstr1_payload": None}

    # --- 3. party GSTIN validity on every outward document -------------------
    stmt = (
        select(Invoice)
        .where(
            Invoice.gstin == gstin,
            Invoice.fp == fp,
            Invoice.direction == InvoiceDirection.SALES,
            Invoice.status.in_((InvoiceStatus.CONFIRMED, InvoiceStatus.LOCKED)),
        )
    )
    outward = (await session.execute(stmt)).scalars().all()
    seen_bad: set[str] = set()
    for inv in outward:
        for gstin_value in (inv.buyer_gstin,):
            if not gstin_value or gstin_value in seen_bad:
                continue
            try:
                validate_gstin(gstin_value)
            except ValueError as exc:
                seen_bad.add(gstin_value)
                _block("INVALID_PARTY_GSTIN", f"buyer_gstin {gstin_value}: {exc}")

    notes_stmt = select(CreditDebitNote).where(
        CreditDebitNote.gstin == gstin,
        CreditDebitNote.fp == fp,
        CreditDebitNote.status == NoteStatus.CONFIRMED,
    )
    for note in (await session.execute(notes_stmt)).scalars().all():
        if not note.buyer_gstin or note.buyer_gstin in seen_bad:
            continue
        try:
            validate_gstin(note.buyer_gstin)
        except ValueError as exc:
            seen_bad.add(note.buyer_gstin)
            _block("INVALID_PARTY_GSTIN", f"note buyer_gstin {note.buyer_gstin}: {exc}")

    # --- 4. missing HSN lines are a warning (HSN summary must be reviewable) -
    hsn_rows = build_hsn_summary_from_payload(payload)
    blank_hsn = [r for r in hsn_rows if not r["hsn_sac"]]
    if blank_hsn:
        _warn(
            "MISSING_HSN",
            f"{sum(r['num_of_lines'] for r in blank_hsn)} outward line(s) have "
            "no HSN/SAC code; HSN summary will be incomplete",
        )

    # --- 5. zero-value outward lines ------------------------------------------
    zero_rows = [r for r in hsn_rows if r["txval_paise"] == 0]
    if zero_rows:
        _warn(
            "ZERO_VALUE_LINES",
            f"{sum(r['num_of_lines'] for r in zero_rows)} outward line(s) "
            "have zero taxable value",
        )

    return {"blocking": blocking, "warnings": warnings, "gstr1_payload": payload}
