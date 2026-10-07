"""GSTR-3B JSON generator and self-validator (integer paise).

Produces the summary return payload from confirmed invoices for a GSTIN + fp.
Money is integer paise everywhere; no float crosses boundaries.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Gstr3bTable4Item(BaseModel):
    """Outward supplies / inward supplies liable to reverse charge (3.1)."""

    model_config = ConfigDict(extra="forbid")
    txval_paise: int = 0
    iamt_paise: int = 0
    camt_paise: int = 0
    samt_paise: int = 0
    csamt_paise: int = 0


class Gstr3bTable5Item(BaseModel):
    """Inter-state outward supplies (3.2)."""

    model_config = ConfigDict(extra="forbid")
    txval_paise: int = 0
    iamt_paise: int = 0


class Gstr3bPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gstin: str = Field(min_length=15, max_length=15)
    fp: str = Field(min_length=6, max_length=6)
    sup_details: dict[str, Any] = Field(default_factory=dict)
    inter_sup: dict[str, Any] = Field(default_factory=dict)
    itc_elg: dict[str, Any] = Field(default_factory=dict)
    inward_sup: dict[str, Any] = Field(default_factory=dict)
    intr_latefee: dict[str, Any] = Field(default_factory=dict)
    interest: dict[str, Any] = Field(default_factory=dict)
    others: dict[str, Any] = Field(default_factory=dict)


def _table_31(invoices: list[Any]) -> dict[str, Any]:
    """Aggregate outward + inward-RCM supplies by nature."""
    osup_zero: dict[str, int] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    osup_nil: dict[str, int] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    osup_reverse: dict[str, int] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    isup_rev: dict[str, int] = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}

    for inv in invoices:
        if inv.direction.value != "SALES":
            continue
        bucket = osup_reverse if inv.rchrg else osup_zero
        bucket["txval"] += inv.total_value_minor
        for line in inv.lines:
            bucket["iamt"] += line.igst_minor
            bucket["camt"] += line.cgst_minor
            bucket["samt"] += line.sgst_minor
            bucket["csamt"] += line.cess_minor

    return {
        "osup_det": {
            "txval_paise": osup_zero["txval"],
            "iamt_paise": osup_zero["iamt"],
            "camt_paise": osup_zero["camt"],
            "samt_paise": osup_zero["samt"],
            "csamt_paise": osup_zero["csamt"],
        },
        "osup_zero": {
            "txval_paise": osup_nil["txval"],
            "iamt_paise": osup_nil["iamt"],
            "camt_paise": osup_nil["camt"],
            "samt_paise": osup_nil["samt"],
            "csamt_paise": osup_nil["csamt"],
        },
        "osup_nil_exmp": {
            "txval_paise": 0,
            "iamt_paise": 0,
            "camt_paise": 0,
            "samt_paise": 0,
            "csamt_paise": 0,
        },
        "osup_rev": {
            "txval_paise": osup_reverse["txval"],
            "iamt_paise": osup_reverse["iamt"],
            "camt_paise": osup_reverse["camt"],
            "samt_paise": osup_reverse["samt"],
            "csamt_paise": osup_reverse["csamt"],
        },
        "isup_rev": {
            "txval_paise": isup_rev["txval"],
            "iamt_paise": isup_rev["iamt"],
            "camt_paise": isup_rev["camt"],
            "samt_paise": isup_rev["samt"],
            "csamt_paise": isup_rev["csamt"],
        },
        "isup_nil_exmp": {
            "txval_paise": 0,
            "iamt_paise": 0,
            "camt_paise": 0,
            "samt_paise": 0,
            "csamt_paise": 0,
        },
        "nc_supp": {
            "txval_paise": 0,
            "iamt_paise": 0,
            "camt_paise": 0,
            "samt_paise": 0,
            "csamt_paise": 0,
        },
    }


def _table_32(invoices: list[Any], gstin_state: str) -> dict[str, Any]:
    """Inter-state supplies to unregistered / composition / UIN persons."""
    unreg: dict[str, int] = {"txval": 0, "iamt": 0}
    comp: dict[str, int] = {"txval": 0, "iamt": 0}
    uin: dict[str, int] = {"txval": 0, "iamt": 0}

    for inv in invoices:
        if inv.direction.value != "SALES":
            continue
        if inv.supply_type.value != "INTER":
            continue
        if not inv.buyer_gstin:
            unreg["txval"] += inv.total_value_minor
            for line in inv.lines:
                unreg["iamt"] += line.igst_minor
        # Composition / UIN buckets require more metadata; leave zero for v1.

    return {
        "unreg_det": {
            "txval_paise": unreg["txval"],
            "iamt_paise": unreg["iamt"],
        },
        "comp_det": {
            "txval_paise": comp["txval"],
            "iamt_paise": comp["iamt"],
        },
        "uin_det": {
            "txval_paise": uin["txval"],
            "iamt_paise": uin["iamt"],
        },
    }


def _itc_eligible(invoices: list[Any]) -> dict[str, Any]:
    """ITC available table 4(A)."""
    itc: dict[str, int] = {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    for inv in invoices:
        if inv.direction.value != "PURCHASE":
            continue
        for line in inv.lines:
            itc["iamt"] += line.igst_minor
            itc["camt"] += line.cgst_minor
            itc["samt"] += line.sgst_minor
            itc["csamt"] += line.cess_minor
    return {
        "itc_avl": [
            {
                "ty": "IMPG",
                "iamt_paise": 0,
                "camt_paise": 0,
                "samt_paise": 0,
                "csamt_paise": 0,
            },
            {
                "ty": "IMPS",
                "iamt_paise": 0,
                "camt_paise": 0,
                "samt_paise": 0,
                "csamt_paise": 0,
            },
            {
                "ty": "ISRC",
                "iamt_paise": itc["iamt"],
                "camt_paise": itc["camt"],
                "samt_paise": itc["samt"],
                "csamt_paise": itc["csamt"],
            },
            {
                "ty": "ISD",
                "iamt_paise": 0,
                "camt_paise": 0,
                "samt_paise": 0,
                "csamt_paise": 0,
            },
        ]
    }


def build_gstr3b_from_invoices(
    gstin: str,
    fp: str,
    invoices: list[Any],
) -> dict[str, Any]:
    """Convert confirmed sales/purchase invoices into a GSTR-3B payload."""
    state_code = gstin[:2]
    payload = Gstr3bPayload(
        gstin=gstin,
        fp=fp,
        sup_details=_table_31(invoices),
        inter_sup=_table_32(invoices, state_code),
        itc_elg=_itc_eligible(invoices),
        inward_sup={
            "isup_details": [
                {
                    "ty": "GST",
                    "inter_paise": 0,
                    "intra_paise": 0,
                },
                {
                    "ty": "NONGST",
                    "inter_paise": 0,
                    "intra_paise": 0,
                },
            ]
        },
        intr_latefee={"iamt_paise": 0, "camt_paise": 0, "samt_paise": 0, "csamt_paise": 0},
        interest={"iamt_paise": 0, "camt_paise": 0, "samt_paise": 0, "csamt_paise": 0},
        others={"iamt_paise": 0, "camt_paise": 0, "samt_paise": 0, "csamt_paise": 0},
    )
    return payload.model_dump()


def validate_gstr3b_payload(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Self-validator: validates dict against the pinned Gstr3bPayload schema."""
    try:
        Gstr3bPayload.model_validate(data)
        return True, None
    except ValidationError as e:
        return False, str(e)
