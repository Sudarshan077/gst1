"""Task 8.4 tests: returns generate pipeline + .xlsx export + HSN summary +
pre-filing validation.

All GSTINs are mod-36-valid synthetic fixtures (make_gstin). Money is
integer paise everywhere. Runs against the live PG:5436 dev DB like every
other route-level suite (conftest wires ASGI client + fakeredis).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.db.models.gst import (
    CreditDebitNote,
    FilingPeriod,
    FilingStatus,
    Invoice,
    InvoiceDirection,
    InvoiceLine,
    InvoiceStatus,
    InvType,
    NoteStatus,
    NoteType,
    SupplyType,
)
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.gstin_fixtures import make_gstin
from tests.v4_helpers import seed_account, seed_open_period

SessionMaker = async_sessionmaker[Any]


async def _seed_confirmed_sales_invoice(
    sessionmaker: SessionMaker,
    gstin: str,
    fp: str,
    *,
    invoice_no: str,
    buyer_gstin: str,
    total_value_minor: int,
    lines: list[dict[str, Any]],
    hsn_sac: str = "998314",
    confirmed_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a CONFIRMED SALES invoice with lines (mirrors review.confirm)."""
    async with sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.SALES,
            supplier_gstin=gstin,
            buyer_gstin=buyer_gstin,
            invoice_no=invoice_no,
            invoice_date=date(2026, 10, 5),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            rchrg=False,
            inv_typ=InvType.R,
            total_value_minor=total_value_minor,
            status=InvoiceStatus.CONFIRMED,
            confirmed_by=confirmed_by,
        )
        session.add(invoice)
        await session.flush()
        for idx, line in enumerate(lines, start=1):
            session.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    line_no=idx,
                    description=line.get("desc", "Item"),
                    hsn_sac=line.get("hsn_sac", hsn_sac),
                    uqc="NOS",
                    qty=Decimal("1"),
                    unit_price_minor=line.get("taxable_value_minor"),
                    gst_rate=Decimal(str(line["gst_rate"])),
                    taxable_value_minor=line["taxable_value_minor"],
                    cgst_minor=line["cgst_minor"],
                    sgst_minor=line["sgst_minor"],
                    igst_minor=line.get("igst_minor", 0),
                    cess_minor=line.get("cess_minor", 0),
                )
            )
        await session.commit()
        return invoice.id


def _line(taxable: int, rate: int, hsn: str | None = "998314") -> dict[str, Any]:
    """One intra-state line dict: tax split HALF_UP like review._compute_line_taxes."""
    tax = (Decimal(taxable) * Decimal(rate) / Decimal(100)).quantize(Decimal("1"))
    half = (Decimal(tax) / Decimal(2)).quantize(Decimal("1"))
    return {
        "taxable_value_minor": taxable,
        "gst_rate": rate,
        "cgst_minor": int(half),
        "sgst_minor": int(tax - half),
        "hsn_sac": hsn,
    }


async def _seed_confirmed_purchase_invoice(
    sessionmaker: SessionMaker,
    gstin: str,
    fp: str,
    *,
    invoice_no: str,
    supplier_gstin: str,
    total_value_minor: int,
    confirmed_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a CONFIRMED PURCHASE invoice (ITC side of 3B)."""
    async with sessionmaker() as session:
        invoice = Invoice(
            gstin=gstin,
            fp=fp,
            direction=InvoiceDirection.PURCHASE,
            supplier_gstin=supplier_gstin,
            buyer_gstin=gstin,
            invoice_no=invoice_no,
            invoice_date=date(2026, 10, 6),
            place_of_supply="27",
            supply_type=SupplyType.INTRA,
            rchrg=False,
            inv_typ=InvType.R,
            total_value_minor=total_value_minor,
            status=InvoiceStatus.CONFIRMED,
            confirmed_by=confirmed_by,
        )
        session.add(invoice)
        await session.commit()
        return invoice.id


async def _seed_confirmed_note(
    sessionmaker: SessionMaker,
    gstin: str,
    fp: str,
    *,
    note_no: str,
    buyer_gstin: str | None,
    taxable_value_minor: int,
    cgst_minor: int,
    sgst_minor: int,
) -> uuid.UUID:
    async with sessionmaker() as session:
        note = CreditDebitNote(
            gstin=gstin,
            fp=fp,
            note_type=NoteType.CDN,
            reason_code="Sales Return",
            buyer_gstin=buyer_gstin,
            taxable_value_minor=taxable_value_minor,
            cgst_minor=cgst_minor,
            sgst_minor=sgst_minor,
            note_no=note_no,
            note_date=date(2026, 10, 7),
            status=NoteStatus.CONFIRMED,
        )
        session.add(note)
        await session.commit()
        return note.id


def _auth(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_generate_returns_per_return_status(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    buyer = make_gstin(state_code="27")
    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="GEN-001",
        buyer_gstin=buyer,
        total_value_minor=118000,
        lines=[_line(100000, 18)],
        confirmed_by=user_id,
    )
    await _seed_confirmed_purchase_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="PUR-001",
        supplier_gstin=make_gstin(state_code="29"),
        total_value_minor=50000,
        confirmed_by=user_id,
    )

    resp = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/returns/generate",
        headers=_auth(tokens),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["gstin"] == gstin
    assert data["fp"] == fp

    gstr1 = data["returns"]["gstr1"]
    assert gstr1["status"] == "READY"
    assert gstr1["invoice_count"] == 1  # sales only — the purchase never enters GSTR-1
    assert gstr1["totals"]["txval_paise"] == 100000
    assert gstr1["totals"]["camt_paise"] == 9000
    assert gstr1["totals"]["samt_paise"] == 9000

    gstr3b = data["returns"]["gstr3b"]
    assert gstr3b["status"] == "READY"
    assert gstr3b["totals"]["txval_paise"] == 118000

    assert data["gstr1_export_id"] is not None
    uuid.UUID(data["gstr1_export_id"])

    # Idempotent: a second generate call also succeeds with the same shape.
    resp2 = await client.post(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/returns/generate",
        headers=_auth(tokens),
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["data"]["returns"]["gstr1"]["status"] == "READY"


async def test_xlsx_export_cells_equal_json_integers(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    buyer = make_gstin(state_code="27")
    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="XLS-001",
        buyer_gstin=buyer,
        total_value_minor=118000,
        lines=[
            _line(100000, 18, hsn="998314"),
            _line(50000, 18, hsn="73269099"),
        ],
        confirmed_by=user_id,
    )
    await _seed_confirmed_note(
        api_sessionmaker,
        gstin,
        fp,
        note_no="CDN-XLS-001",
        buyer_gstin=buyer,
        taxable_value_minor=10000,
        cgst_minor=900,
        sgst_minor=900,
    )

    headers = _auth(tokens)

    # --- GSTR-1: JSON first, then xlsx; cell values must equal the JSON ints.
    jresp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/export.json",
        headers=headers,
    )
    assert jresp.status_code == 200, jresp.text
    payload = jresp.json()["data"]

    xresp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/export.xlsx",
        headers=headers,
    )
    assert xresp.status_code == 200, xresp.text
    assert "spreadsheetml" in xresp.headers["content-type"]
    wb = load_workbook(io.BytesIO(xresp.content))
    assert "B2B" in wb.sheetnames
    assert "HSN Summary" in wb.sheetnames
    assert "CDNR" in wb.sheetnames

    b2b_ws = wb["B2B"]
    # Header block is 4 rows (title + gstin + fp + blank) + 1 header row.
    row = [c for c in next(b2b_ws.iter_rows(min_row=6, max_row=6, values_only=True))]
    assert row[0] == buyer
    assert row[3] == payload["b2b"][0]["inv"][0]["val_paise"] == 118000
    assert row[9] == payload["b2b"][0]["inv"][0]["itms"][0]["txval_paise"] == 100000
    assert row[10] == payload["b2b"][0]["inv"][0]["itms"][0]["iamt_paise"] == 0
    assert row[11] == payload["b2b"][0]["inv"][0]["itms"][0]["camt_paise"] == 9000
    assert row[12] == payload["b2b"][0]["inv"][0]["itms"][0]["samt_paise"] == 9000

    # Every *_paise JSON integer appears identically in the sheet. The B2B
    # sheet renders ONE ROW PER LINE ITEM, so flatten both sides and compare
    # pairwise: (txval, iamt, camt, samt, csamt) at columns 9..13.
    json_items = [
        item
        for entry in payload["b2b"]
        for inv in entry["inv"]
        for item in inv["itms"]
    ]
    xls_rows = list(b2b_ws.iter_rows(min_row=6, values_only=True))
    xls_item_rows = [r for r in xls_rows if r[6] != "-"][: len(json_items)]
    assert len(xls_item_rows) == len(json_items)
    for xls_row, item in zip(xls_item_rows, json_items, strict=True):
        assert xls_row[9] == item["txval_paise"]
        assert xls_row[10] == item["iamt_paise"]
        assert xls_row[11] == item["camt_paise"]
        assert xls_row[12] == item["samt_paise"]
        assert xls_row[13] == item["csamt_paise"]
        assert xls_row[1] == payload["b2b"][0]["inv"][0]["inum"]

    # CDNR sheet carries the note row.
    cdnr_ws = wb["CDNR"]
    cdnr_rows = list(cdnr_ws.iter_rows(min_row=6, values_only=True))
    assert any(r[1] == "CDN-XLS-001" and r[5] == 10000 for r in cdnr_rows)

    # --- GSTR-3B xlsx.
    x3b = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr3b/export.xlsx",
        headers=headers,
    )
    assert x3b.status_code == 200, x3b.text
    assert "spreadsheetml" in x3b.headers["content-type"]
    wb3b = load_workbook(io.BytesIO(x3b.content))
    ws_sup = wb3b["Supplies"]
    osup_row = [r for r in ws_sup.iter_rows(values_only=True) if r[0] == "osup_det"]
    assert osup_row, "osup_det section must be present"
    assert osup_row[0][1] == 118000  # total_value_minor of the sales invoice


async def test_hsn_summary_reconciles_to_gstr1(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    buyer = make_gstin(state_code="27")
    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="HSN-001",
        buyer_gstin=buyer,
        total_value_minor=236000,
        lines=[
            _line(100000, 18, hsn="998314"),
            _line(100000, 18, hsn="998314"),
            _line(36000, 18, hsn="73269099"),
        ],
        confirmed_by=user_id,
    )

    headers = _auth(tokens)
    jresp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/export.json",
        headers=headers,
    )
    assert jresp.status_code == 200, jresp.text
    payload = jresp.json()["data"]

    hresp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/gstr1/hsn-summary",
        headers=headers,
    )
    assert hresp.status_code == 200, hresp.text
    data = hresp.json()["data"]
    rows = data["rows"]
    totals = data["totals"]

    # HSN rows reconcile to the GSTR-1 payload line-by-line.
    json_txval = 0
    json_iamt = 0
    json_camt = 0
    json_samt = 0
    for entry in payload["b2b"]:
        for inv in entry["inv"]:
            for item in inv["itms"]:
                json_txval += item["txval_paise"]
                json_iamt += item["iamt_paise"]
                json_camt += item["camt_paise"]
                json_samt += item["samt_paise"]

    assert totals["txval_paise"] == json_txval == 236000
    assert totals["iamt_paise"] == json_iamt
    # 236000 taxable @18% -> 42480 tax, split HALF_UP: cgst = sgst = 21240.
    assert totals["camt_paise"] == json_camt == 21240
    assert totals["samt_paise"] == json_samt == 21240

    by_hsn = {r["hsn_sac"]: r for r in rows}
    assert by_hsn["998314"]["txval_paise"] == 200000
    assert by_hsn["998314"]["num_of_lines"] == 2
    assert by_hsn["73269099"]["txval_paise"] == 36000
    assert by_hsn["73269099"]["num_of_lines"] == 1


async def test_validation_clean_period_and_filed_conflict(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="VAL-001",
        buyer_gstin=make_gstin(state_code="27"),
        total_value_minor=118000,
        lines=[_line(100000, 18)],
        confirmed_by=user_id,
    )

    headers = _auth(tokens)
    resp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/returns/validation",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["blocking"] == []
    assert data["warnings"] == []

    # File the period → the same call must return a blocking entry.
    async with api_sessionmaker() as session:
        period = await session.get(FilingPeriod, (gstin, fp))
        assert period is not None
        period.status = FilingStatus.FILED
        period.filed_at = datetime.now(UTC)
        period.filed_by = user_id
        await session.commit()

    resp2 = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/returns/validation",
        headers=headers,
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()["data"]
    assert len(data2["blocking"]) == 1
    assert data2["blocking"][0]["rule"] == "PERIOD_ALREADY_FILED"


async def test_validation_warns_on_missing_hsn(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="VAL-HSN-001",
        buyer_gstin=make_gstin(state_code="27"),
        total_value_minor=118000,
        lines=[_line(100000, 18, hsn=None)],
        confirmed_by=user_id,
    )

    resp = await client.get(
        f"/api/v1/gst-accounts/{gstin}/months/{fp}/returns/validation",
        headers=_auth(tokens),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["blocking"] == []
    warn_rules = [w["rule"] for w in data["warnings"]]
    assert "MISSING_HSN" in warn_rules


async def test_guard_outsider_gets_404_on_all_new_routes(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    await seed_open_period(api_sessionmaker, gstin, fp)

    other_tokens, _ = await seed_account(client, api_sessionmaker, state_code="29")
    other_headers = {"Authorization": f"Bearer {other_tokens['access_token']}"}

    base = f"/api/v1/gst-accounts/{gstin}/months/{fp}"
    for method, path in (
        ("POST", "/returns/generate"),
        ("GET", "/gstr1/export.xlsx"),
        ("GET", "/gstr3b/export.xlsx"),
        ("GET", "/gstr1/hsn-summary"),
        ("GET", "/returns/validation"),
    ):
        resp = await client.request(method, f"{base}{path}", headers=other_headers)
        assert resp.status_code == 404, (method, path, resp.text)
        assert resp.json()["error"]["code"] == "GSTIN_NOT_FOUND"


async def test_validation_service_branches_direct(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Direct service-level coverage of the validation branches the route
    tests reach only through untraced ASGI frames (blocking party-GSTIN,
    filed period, and the payload dict presence)."""
    from app.services.returns.validation import validate_period_for_filing

    tokens, account = await seed_account(client, api_sessionmaker, state_code="27")
    gstin = account.gstin
    fp = "102026"
    user_id = _user_id(tokens)
    await seed_open_period(api_sessionmaker, gstin, fp)

    # Outward invoice with a checksum-INVALID buyer GSTIN -> blocking entry.
    bad_buyer = make_gstin(state_code="27")[:14] + (
        "0" if make_gstin(state_code="27")[14] != "0" else "1"
    )
    await _seed_confirmed_sales_invoice(
        api_sessionmaker,
        gstin,
        fp,
        invoice_no="VAL-BAD-001",
        buyer_gstin=bad_buyer,
        total_value_minor=118000,
        lines=[_line(100000, 18)],
        confirmed_by=user_id,
    )

    async with api_sessionmaker() as session:
        result = await validate_period_for_filing(session, gstin, fp)
        rules = [b["rule"] for b in result["blocking"]]
        assert "INVALID_PARTY_GSTIN" in rules
        assert result["gstr1_payload"] is not None
        # filed-period branch
        period = await session.get(FilingPeriod, (gstin, fp))
        period.status = FilingStatus.FILED
        await session.commit()
        result2 = await validate_period_for_filing(session, gstin, fp)
        assert any(b["rule"] == "PERIOD_ALREADY_FILED" for b in result2["blocking"])


async def test_generate_unknown_form_rejected(api_sessionmaker: SessionMaker) -> None:
    """load_return_payload with an unsupported form is a 422-shaped error."""
    from app.api.errors import ServiceError
    from app.services.returns.pipeline import load_return_payload

    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await load_return_payload(session, make_gstin(), "102026", "gstr9")
        assert exc.value.status_code == 422


def _user_id(tokens: dict[str, Any]) -> uuid.UUID:
    from app.core.auth.tokens import verify_access_token

    return verify_access_token(tokens["access_token"])
