from datetime import datetime, date
from typing import Any
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import difflib
from app.db.models.gst import (
    Gstr2bStatement, Gstr2bEntry, Gstr2bSource, MatchStatus, 
    ItcReconciliation, Invoice, InvoiceDirection
)

async def import_gstr2b(session: AsyncSession, gstin: str, fp: str, payload: dict[str, Any], user_id: uuid.UUID) -> Gstr2bStatement:
    # 1. Create statement
    statement = Gstr2bStatement(
        gstin=gstin, 
        fp=fp, 
        source=Gstr2bSource.PORTAL_UPLOAD, 
        raw_minio_key=f"gstr2b/{gstin}/{fp}/{uuid.uuid4()}.json",
        imported_by=user_id
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
            doc_type=entry_data["doc_type"]
        )
        session.add(entry)
        
    await session.commit()
    return statement

async def reconcile_itc(session: AsyncSession, gstin: str, fp: str) -> list[ItcReconciliation]:
    # 1. Get GSTR-2B entries and Purchase Invoices
    stmt_statement = select(Gstr2bStatement).where(and_(Gstr2bStatement.gstin == gstin, Gstr2bStatement.fp == fp))
    result_statement = await session.execute(stmt_statement)
    statement = result_statement.scalar_one_or_none()
    
    if not statement:
        return []

    stmt_entries = select(Gstr2bEntry).where(Gstr2bEntry.statement_id == statement.id)
    result_entries = await session.execute(stmt_entries)
    entries = result_entries.scalars().all()
    
    stmt_invoices = select(Invoice).where(and_(Invoice.gstin == gstin, Invoice.fp == fp, Invoice.direction == InvoiceDirection.PURCHASE))
    result_invoices = await session.execute(stmt_invoices)
    invoices = result_invoices.scalars().all()
    
    reconciliations = []
    matched_entry_ids = set()
    matched_invoice_ids = set()
    
    # Simple matching engine
    # MATCHED: (gstin, invoice_no, taxable_value)
    for entry in entries:
        for invoice in invoices:
            if invoice.id in matched_invoice_ids: continue
            
            # Simple match
            if entry.supplier_gstin == invoice.supplier_gstin and entry.invoice_no == invoice.invoice_no:
                if entry.taxable_value_minor == invoice.total_value_minor:
                    recon = ItcReconciliation(
                        gstin=gstin, fp=fp, purchase_invoice_id=invoice.id, 
                        gstr2b_entry_id=entry.id, match_status=MatchStatus.MATCHED,
                        confidence=1.0, remarks="Exact match"
                    )
                    reconciliations.append(recon)
                    matched_entry_ids.add(entry.id)
                    matched_invoice_ids.add(invoice.id)
                    break
                elif abs(entry.taxable_value_minor - invoice.total_value_minor) < 100:
                    recon = ItcReconciliation(
                        gstin=gstin, fp=fp, purchase_invoice_id=invoice.id, 
                        gstr2b_entry_id=entry.id, match_status=MatchStatus.PROBABLE,
                        confidence=0.8, remarks="Amount mismatch"
                    )
                    reconciliations.append(recon)
                    matched_entry_ids.add(entry.id)
                    matched_invoice_ids.add(invoice.id)
                    break
                else:
                    recon = ItcReconciliation(
                        gstin=gstin, fp=fp, purchase_invoice_id=invoice.id, 
                        gstr2b_entry_id=entry.id, match_status=MatchStatus.UNMATCHED,
                        confidence=0.0, remarks="Amount mismatch"
                    )
                    reconciliations.append(recon)
                    matched_entry_ids.add(entry.id)
                    matched_invoice_ids.add(invoice.id)
                    break
            # Fuzzy match (PROBABLE)
            elif entry.supplier_gstin == invoice.supplier_gstin and difflib.SequenceMatcher(None, entry.invoice_no, invoice.invoice_no).ratio() > 0.8:
                recon = ItcReconciliation(
                    gstin=gstin, fp=fp, purchase_invoice_id=invoice.id, 
                    gstr2b_entry_id=entry.id, match_status=MatchStatus.PROBABLE,
                    confidence=0.6, remarks="Fuzzy invoice match"
                )
                reconciliations.append(recon)
                matched_entry_ids.add(entry.id)
                matched_invoice_ids.add(invoice.id)
                break
    
    # MISSING_IN_2B: Present in Books, not in 2B
    for invoice in invoices:
        if invoice.id not in matched_invoice_ids:
            recon = ItcReconciliation(
                gstin=gstin, fp=fp, purchase_invoice_id=invoice.id,
                gstr2b_entry_id=None, match_status=MatchStatus.MISSING_IN_2B,
                confidence=0.0, remarks="Missing in GSTR-2B"
            )
            reconciliations.append(recon)

    # MISSING_IN_BOOKS: Present in 2B, not in Books
    for entry in entries:
        if entry.id not in matched_entry_ids:
            recon = ItcReconciliation(
                gstin=gstin, fp=fp, purchase_invoice_id=None,
                gstr2b_entry_id=entry.id, match_status=MatchStatus.MISSING_IN_BOOKS,
                confidence=0.0, remarks="Missing in books"
            )
            reconciliations.append(recon)
            
    session.add_all(reconciliations)
    await session.commit()
    return reconciliations
