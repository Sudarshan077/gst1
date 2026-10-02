"""documents dedupe unique index + append-only app role grants (v4)

Revision ID: b31f7a20c9e4
Revises: 23df76009888
Create Date: 2026-10-02

Two things the v4 rebaseline dropped and this revision restores on the v4
table inventory:

1. `extraction.documents` dedupe is enforced in the DB, not only in the
   service: UNIQUE (gstin, fp, sha256). v4 keys documents straight off the
   GSTIN, so the old registration_id-keyed index could not carry over.
2. SECURITY_AND_ACCESS.md §5 — `core.audit_logs` must be INSERT-only for the
   application role. Creates the `gst_app` LOGIN role (dev password, override
   with GST_APP_ROLE_PASSWORD) and grants DML on every v4 table except
   audit_logs, which gets INSERT only.
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "b31f7a20c9e4"
down_revision: str | Sequence[str] | None = "23df76009888"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# literal so this revision cannot silently drift with model changes.
_SCHEMAS: tuple[str, ...] = ("core", "gst", "extraction")
_TABLES: dict[str, tuple[str, ...]] = {
    "core": ("users", "gst_accounts", "user_gst_access", "audit_logs"),
    "gst": (
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
    ),
    "extraction": ("documents", "extraction_jobs", "invoice_drafts"),
}

DEFAULT_APP_ROLE_PASSWORD = "gst_app_dev_pass"  # noqa: S105

_ROLE_DDL_TEMPLATE = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gst_app') THEN
                CREATE ROLE gst_app LOGIN PASSWORD __PW__;
            ELSE
                ALTER ROLE gst_app LOGIN PASSWORD __PW__;
            END IF;
        END $$;
        """


def _role_password() -> str:
    return os.environ.get("GST_APP_ROLE_PASSWORD", DEFAULT_APP_ROLE_PASSWORD)


def _q(value: str) -> str:
    """Render a SQL string literal safely (DDL cannot take bind parameters)."""
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    conn = op.get_bind()
    op.create_index(
        "uq_documents_gstin_fp_sha256",
        "documents",
        ["gstin", "fp", "sha256"],
        unique=True,
        schema="extraction",
    )

    conn.exec_driver_sql(_ROLE_DDL_TEMPLATE.replace("__PW__", _q(_role_password())))
    for schema, tables in _TABLES.items():
        for table in tables:
            conn.exec_driver_sql(f"REVOKE ALL ON {schema}.{table} FROM PUBLIC")
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO gst_app")
    for schema, tables in _TABLES.items():
        for table in tables:
            if (schema, table) == ("core", "audit_logs"):
                conn.exec_driver_sql(f"GRANT INSERT ON {schema}.{table} TO gst_app")
            else:
                conn.exec_driver_sql(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO gst_app"
                )
    # Sequences: v4 uses UUID keys, but grant for future serial columns.
    for schema in _SCHEMAS:
        conn.exec_driver_sql(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO gst_app"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for schema, tables in _TABLES.items():
        for table in tables:
            conn.exec_driver_sql(f"REVOKE ALL ON {schema}.{table} FROM gst_app")
        conn.exec_driver_sql(f"REVOKE USAGE ON SCHEMA {schema} FROM gst_app")
    op.drop_index(
        "uq_documents_gstin_fp_sha256", table_name="documents", schema="extraction"
    )
    # The role itself is cluster-level and shared across databases: it survives.
