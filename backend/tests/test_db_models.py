"""Task 0.3 verification: v4 ORM metadata contract.

Proves the model layer itself matches TECHNICAL_ARCHITECTURE §3 v4.0:
  gst_accounts.gstin is the primary key;
  user_gst_access links users.id -> gst_accounts.gstin;
  the ORM registers exactly the 20 v4 tables across core/gst/extraction;
  money is integer paise everywhere.

Note: conftest imports auth_helpers -> app.main (v2-era routers mid-v4
migration, out of 0.3 scope), so this module never imports conftest fixtures
that drag app.main in; the ORM import is self-contained.
"""

from __future__ import annotations

from app.db import base as app_db_base
from app.db.base import Base

app_db_base.all_models()

EXPECTED_TABLES: dict[str, set[str]] = {
    "core": {
        "users",
        "gst_accounts",
        "user_gst_access",
        "audit_logs",
    },
    "gst": {
        "document_series",
        "invoices",
        "invoice_lines",
        "credit_debit_notes",
        "filing_periods",
        "gstr1_exports",
        "gstr1a_amendments",
        "e_invoices",
        "gstr3b_exports",
        "gstr2b_statements",
        "gstr2b_entries",
        "itc_reconciliation",
        "notifications",
    },
    "extraction": {
        "documents",
        "extraction_jobs",
        "invoice_drafts",
    },
}


def test_model_metadata_registers_all_20_v4_tables() -> None:
    """The ORM registers exactly the doc's 20 v4 tables across 3 schemas."""

    by_schema: dict[str, set[str]] = {}
    for table in Base.metadata.sorted_tables:
        assert table.schema in EXPECTED_TABLES, f"unexpected schema {table.schema}"
        by_schema.setdefault(table.schema, set()).add(table.name)
    assert by_schema == EXPECTED_TABLES


def test_gst_accounts_gstin_is_primary_key() -> None:
    """core.gst_accounts PK is the gstin String(15) — the primary entity key."""
    gst_accounts = Base.metadata.tables["core.gst_accounts"]
    pk_cols = [c.name for c in gst_accounts.primary_key.columns]
    assert pk_cols == ["gstin"]
    assert gst_accounts.columns["gstin"].type.length == 15
    # pan derived from gstin[2:12]
    assert gst_accounts.columns["pan"].type.length == 10


def test_user_gst_access_links_users_to_gstin() -> None:
    """user_gst_access: FKs users.id + gst_accounts.gstin, unique (user_id, gstin)."""
    access = Base.metadata.tables["core.user_gst_access"]
    fk_targets = {fk.target_fullname for fk in access.foreign_keys}
    assert "core.users.id" in fk_targets, fk_targets
    assert "core.gst_accounts.gstin" in fk_targets, fk_targets
    uq = {
        tuple(uq.columns.keys())
        for uq in access.constraints
        if uq.__class__.__name__ == "UniqueConstraint"
    }
    assert ("user_id", "gstin") in uq, uq


def test_gst_schema_tables_keyed_by_gstin() -> None:
    """Every registration-scoped gst.* table carries a gstin FK to core —
    no registration_id/business_id surrogate anywhere (v4 unified model)."""
    gstin_fks = {
        "gst.document_series",
        "gst.invoices",
        "gst.credit_debit_notes",
        "gst.filing_periods",
        "gst.gstr1_exports",
        "gst.gstr3b_exports",
        "gst.gstr2b_statements",
        "gst.itc_reconciliation",
        "gst.notifications",
    }
    for key in gstin_fks:
        table = Base.metadata.tables[key]
        fk_targets = {fk.target_fullname for fk in table.foreign_keys}
        assert "core.gst_accounts.gstin" in fk_targets, f"{key}: {fk_targets}"
        assert "registration_id" not in table.columns, key
        assert "business_id" not in table.columns, key


def test_filing_period_composite_key_gstin_fp() -> None:
    """filing_periods composite PK is (gstin, fp) in v4 (was registration_id)."""
    fp = Base.metadata.tables["gst.filing_periods"]
    pk_cols = {c.name for c in fp.primary_key.columns}
    assert pk_cols == {"gstin", "fp"}


def test_invoice_lock_columns_and_enum() -> None:
    """invoices.status enum carries DRAFT/CONFIRMED/LOCKED (post-filing lock)."""
    from app.db.models.gst import InvoiceStatus

    assert [s.value for s in InvoiceStatus] == ["DRAFT", "CONFIRMED", "LOCKED"]
    invoices = Base.metadata.tables["gst.invoices"]
    assert "status" in invoices.columns
    assert "confirmed_at" in invoices.columns


def test_money_columns_are_integer_paise() -> None:
    """No float money anywhere: *_minor columns must be Integer/BigInteger-typed."""
    from sqlalchemy import BigInteger, Integer

    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.name.endswith("_minor"):
                assert isinstance(column.type, (Integer, BigInteger)), (
                    f"{table.schema}.{table.name}.{column.name} is "
                    f"{column.type!r}, expected Integer/BigInteger (paise rule)"
                )
