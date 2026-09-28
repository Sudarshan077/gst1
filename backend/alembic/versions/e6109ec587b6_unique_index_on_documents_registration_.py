"""unique index on documents registration fp sha256

Revision ID: e6109ec587b6
Revises: 6c4b85f9c8d2
Create Date: 2026-09-28 13:09:37.667095

Adds a backstop unique index on (registration_id, fp, sha256) in the
extraction.documents table per API_SPEC §19 + SECURITY_AND_ACCESS.md §6.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6109ec587b6"
down_revision: str | Sequence[str] | None = "6c4b85f9c8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_documents_reg_fp_sha256",
        "documents",
        ["registration_id", "fp", "sha256"],
        unique=True,
        schema="extraction",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_documents_reg_fp_sha256",
        table_name="documents",
        schema="extraction",
    )
