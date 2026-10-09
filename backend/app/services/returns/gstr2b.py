from __future__ import annotations

import difflib
import uuid
from datetime import date
from typing import Any

from app.api.errors import ServiceError
from app.db.models.gst import (
    Gstr2bEntry,
    Gstr2bSource,
    Gstr2bStatement,
    Invoice,
    InvoiceDirection,
    ItcReconciliation,
    MatchStatus,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def import_gstr2b(
    session: AsyncSession,
    gstin: str,
    fp: str,
    payload: dict[str, Any],
    user_id: uuid.UUID,
) -> Gstr2bStatement:
    # 1. Create statement
    statement = Gstr2bStatement(
        gstin=gstin,
        fp=fp,
        source=Gstr2bSource.PORTAL_UPLOAD,
        raw_minio_key=f"gstr2b/{gstin}/{fp}/{uuid.uuid4()}.json",
        imported_by=user_id,
    )
    session.add(statement)
    await session.flush()

    # 2. Parse entries (simplified for now)
    for entry_data in payload.get("entries", []):
        invoice_date = entry_data["invoice_date"]
        if isinstance(invoice_date, str):
            invoice_date = date.fromisoformat(invoice_date)

        entry = Gstr2bEntry(
            statement_id=statement.id,
            supplier_gstin=entry_data["supplier_gstin"],
            invoice_no=entry_data["invoice_no"],
            invoice_date=invoice_date,
            taxable_value_minor=entry_data["taxable_value_minor"],
            cgst_minor=entry_data.get("cgst_minor", 0),
            sgst_minor=entry_data.get("sgst_minor", 0),
            igst_minor=entry_data.get("igst_minor", 0),
            cess_minor=entry_data.get("cess_minor", 0),
            itc_eligible=entry_data.get("itc_eligible", True),
            doc_type=entry_data["doc_type"],
        )
        session.add(entry)

    await session.commit()
    return statement


async def reconcile_itc(
    session: AsyncSession, gstin: str, fp: str
) -> list[ItcReconciliation]:
    # 1. Get GSTR-2B entries and Purchase Invoices
    stmt_statement = select(Gstr2bStatement).where(
        and_(Gstr2bStatement.gstin == gstin, Gstr2bStatement.fp == fp)
    )
    result_statement = await session.execute(stmt_statement)
    statement = result_statement.scalar_one_or_none()

    if not statement:
        return []

    stmt_entries = select(Gstr2bEntry).where(
        Gstr2bEntry.statement_id == statement.id
    )
    result_entries = await session.execute(stmt_entries)
    entries = result_entries.scalars().all()

    stmt_invoices = select(Invoice).where(
        and_(
            Invoice.gstin == gstin,
            Invoice.fp == fp,
            Invoice.direction == InvoiceDirection.PURCHASE,
        )
    )
    result_invoices = await session.execute(stmt_invoices)
    invoices = result_invoices.scalars().all()

    reconciliations: list[ItcReconciliation] = []
    matched_entry_ids: set[uuid.UUID] = set()
    matched_invoice_ids: set[uuid.UUID] = set()

    # Simple matching engine
    # MATCHED: (gstin, invoice_no, taxable_value)
    for entry in entries:
        for invoice in invoices:
            if invoice.id in matched_invoice_ids:
                continue

            # Simple match
            if (
                entry.supplier_gstin == invoice.supplier_gstin
                and entry.invoice_no == invoice.invoice_no
            ):
                if entry.taxable_value_minor == invoice.total_value_minor:
                    recon = ItcReconciliation(
                        gstin=gstin,
                        fp=fp,
                        purchase_invoice_id=invoice.id,
                        gstr2b_entry_id=entry.id,
                        match_status=MatchStatus.MATCHED,
                        confidence=1.0,
                        remarks="Exact match",
                    )
                    reconciliations.append(recon)
                    matched_entry_ids.add(entry.id)
                    matched_invoice_ids.add(invoice.id)
                    break
                if abs(entry.taxable_value_minor - invoice.total_value_minor) < 100:
                    recon = ItcReconciliation(
                        gstin=gstin,
                        fp=fp,
                        purchase_invoice_id=invoice.id,
                        gstr2b_entry_id=entry.id,
                        match_status=MatchStatus.PROBABLE,
                        confidence=0.8,
                        remarks="Amount mismatch",
                    )
                    reconciliations.append(recon)
                    matched_entry_ids.add(entry.id)
                    matched_invoice_ids.add(invoice.id)
                    break
                recon = ItcReconciliation(
                    gstin=gstin,
                    fp=fp,
                    purchase_invoice_id=invoice.id,
                    gstr2b_entry_id=entry.id,
                    match_status=MatchStatus.UNMATCHED,
                    confidence=0.0,
                    remarks="Amount mismatch",
                )
                reconciliations.append(recon)
                matched_entry_ids.add(entry.id)
                matched_invoice_ids.add(invoice.id)
                break
            # Fuzzy match (PROBABLE)
            ratio = difflib.SequenceMatcher(
                None, entry.invoice_no, invoice.invoice_no
            ).ratio()
            if (
                entry.supplier_gstin == invoice.supplier_gstin
                and ratio > 0.8
            ):
                recon = ItcReconciliation(
                    gstin=gstin,
                    fp=fp,
                    purchase_invoice_id=invoice.id,
                    gstr2b_entry_id=entry.id,
                    match_status=MatchStatus.PROBABLE,
                    confidence=0.6,
                    remarks="Fuzzy invoice match",
                )
                reconciliations.append(recon)
                matched_entry_ids.add(entry.id)
                matched_invoice_ids.add(invoice.id)
                break

    # MISSING_IN_2B: Present in Books, not in 2B
    for invoice in invoices:
        if invoice.id not in matched_invoice_ids:
            recon = ItcReconciliation(
                gstin=gstin,
                fp=fp,
                purchase_invoice_id=invoice.id,
                gstr2b_entry_id=None,
                match_status=MatchStatus.MISSING_IN_2B,
                confidence=0.0,
                remarks="Missing in GSTR-2B",
            )
            reconciliations.append(recon)

    # MISSING_IN_BOOKS: Present in 2B, not in Books
    for entry in entries:
        if entry.id not in matched_entry_ids:
            recon = ItcReconciliation(
                gstin=gstin,
                fp=fp,
                purchase_invoice_id=None,
                gstr2b_entry_id=entry.id,
                match_status=MatchStatus.MISSING_IN_BOOKS,
                confidence=0.0,
                remarks="Missing in books",
            )
            reconciliations.append(recon)

    session.add_all(reconciliations)
    await session.commit()
    return reconciliations


# --------------------------------------------------------------- report (9.4)

_ZERO_TAX: dict[str, int] = {"cgst": 0, "sgst": 0, "igst": 0, "cess": 0}


def _tax_bucket(
    cgst: int, sgst: int, igst: int, cess: int
) -> dict[str, int]:
    """Integer-paise tax bucket with an explicit total (never a float)."""
    return {
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "cess_paise": cess,
        "total_paise": cgst + sgst + igst + cess,
    }


def _books_side(invoice: Invoice) -> dict[str, Any]:
    """Books row: invoice-level money + the line-item tax breakdown."""
    taxable = 0
    cgst = 0
    sgst = 0
    igst = 0
    cess = 0
    for line in invoice.lines:
        taxable += line.taxable_value_minor
        cgst += line.cgst_minor
        sgst += line.sgst_minor
        igst += line.igst_minor
        cess += line.cess_minor
    total = invoice.total_value_minor
    return {
        "invoice_id": str(invoice.id),
        "invoice_no": invoice.invoice_no,
        "invoice_date": invoice.invoice_date.isoformat(),
        "supplier_gstin": invoice.supplier_gstin,
        "buyer_gstin": invoice.buyer_gstin,
        "place_of_supply": invoice.place_of_supply,
        "status": invoice.status.value,
        "taxable_value_paise": taxable,
        "total_value_paise": total,
        **_tax_bucket(cgst, sgst, igst, cess),
    }


def _gstr2b_side(entry: Gstr2bEntry) -> dict[str, Any]:
    """2B row: the statement's figures for the same document."""
    return {
        "entry_id": str(entry.id),
        "invoice_no": entry.invoice_no,
        "invoice_date": entry.invoice_date.isoformat(),
        "supplier_gstin": entry.supplier_gstin,
        "doc_type": entry.doc_type,
        "itc_eligible": entry.itc_eligible,
        "taxable_value_paise": entry.taxable_value_minor,
        **_tax_bucket(
            entry.cgst_minor, entry.sgst_minor, entry.igst_minor, entry.cess_minor
        ),
    }


_TAX_KEYS: tuple[str, ...] = (
    "cgst_paise",
    "sgst_paise",
    "igst_paise",
    "cess_paise",
    "total_paise",
)


def _sum_tax_buckets(buckets: list[dict[str, int]]) -> dict[str, int]:
    total: dict[str, int] = {key: 0 for key in _TAX_KEYS}
    for bucket in buckets:
        for key in _TAX_KEYS:
            total[key] += bucket[key]
    return total


async def build_itc_report(
    session: AsyncSession,
    gstin: str,
    fp: str,
    status: str | None = None,
) -> dict[str, Any]:
    """Books-vs-2B reconciliation report for one (gstin, fp).

    API_SPECIFICATION.md §9 `GET /gst-accounts/{gstin}/months/{fp}/itc/report`
    — the reconciliation rows enriched with BOTH sides' figures so the
    dashboard can render the side-by-side table and the GSTR-3B ITC prefill
    card. Money is integer paise on both sides.

    `status` filters the returned `rows` only; `summary.counts` always counts
    every status so the UI can label its filter chips.
    """
    statement = (
        await session.execute(
            select(Gstr2bStatement).where(
                and_(Gstr2bStatement.gstin == gstin, Gstr2bStatement.fp == fp)
            )
        )
    ).scalar_one_or_none()

    recons = list(
        (
            await session.execute(
                select(ItcReconciliation).where(
                    ItcReconciliation.gstin == gstin,
                    ItcReconciliation.fp == fp,
                )
            )
        )
        .scalars()
        .all()
    )

    invoice_ids = {r.purchase_invoice_id for r in recons if r.purchase_invoice_id}

    entries: dict[uuid.UUID, Gstr2bEntry] = {}
    entry_count = 0
    if statement is not None:
        statement_entries = (
            await session.execute(
                select(Gstr2bEntry).where(Gstr2bEntry.statement_id == statement.id)
            )
        ).scalars().all()
        entries = {e.id: e for e in statement_entries}
        entry_count = len(statement_entries)
    else:
        entry_ids = {r.gstr2b_entry_id for r in recons if r.gstr2b_entry_id}
        if entry_ids:
            rows_e = (
                await session.execute(
                    select(Gstr2bEntry).where(Gstr2bEntry.id.in_(entry_ids))
                )
            ).scalars().all()
            entries = {e.id: e for e in rows_e}

    invoices: dict[uuid.UUID, Invoice] = {}
    if invoice_ids:
        rows = (
            await session.execute(
                select(Invoice)
                .options(selectinload(Invoice.lines))
                .where(Invoice.id.in_(invoice_ids))
            )
        ).scalars().all()
        invoices = {inv.id: inv for inv in rows}

    counts: dict[str, int] = {s.value: 0 for s in MatchStatus}
    report_rows: list[dict[str, Any]] = []
    books_tax: list[dict[str, int]] = []
    gstr2b_tax: list[dict[str, int]] = []

    for recon in recons:
        counts[recon.match_status.value] += 1
        invoice = (
            invoices.get(recon.purchase_invoice_id)
            if recon.purchase_invoice_id is not None
            else None
        )
        entry = (
            entries.get(recon.gstr2b_entry_id)
            if recon.gstr2b_entry_id is not None
            else None
        )
        books = _books_side(invoice) if invoice is not None else None
        two_b = _gstr2b_side(entry) if entry is not None else None
        if books is not None:
            books_tax.append({k: v for k, v in books.items() if k.endswith("_paise")})
        if two_b is not None and two_b["itc_eligible"]:
            gstr2b_tax.append({k: v for k, v in two_b.items() if k.endswith("_paise")})

        report_rows.append(
            {
                "id": str(recon.id),
                "match_status": recon.match_status.value,
                "confidence": float(recon.confidence) if recon.confidence is not None else None,
                "remarks": recon.remarks,
                "books": books,
                "gstr2b": two_b,
            }
        )

    all_counts = dict(counts)
    all_counts["total"] = len(recons)

    filtered = report_rows
    if status is not None:
        valid = {s.value for s in MatchStatus}
        if status not in valid:
            raise ServiceError(
                f"unknown match status: {status}", 422, "VALIDATION_ERROR"
            )
        filtered = [r for r in report_rows if r["match_status"] == status]

    books_itc = _sum_tax_buckets(books_tax)
    gstr2b_itc = _sum_tax_buckets(gstr2b_tax)

    return {
        "gstin": gstin,
        "fp": fp,
        "statement": (
            {
                "id": str(statement.id),
                "source": statement.source.value,
                "downloaded_at": statement.downloaded_at.isoformat(),
                "entry_count": entry_count,
            }
            if statement is not None
            else None
        ),
        "rows": filtered,
        "summary": {
            "counts": all_counts,
            "books_itc_paise": books_itc,
            "gstr2b_itc_paise": gstr2b_itc,
            "delta_itc_paise": {
                key: books_itc[key] - gstr2b_itc[key] for key in books_itc
            },
        },
    }
