"""make core.users.email NOT NULL and backfill existing rows

Revision ID: 8483441721c7
Revises: 6ebf53cccd9c
Create Date: 2026-10-07 08:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8483441721c7'
down_revision: Union[str, Sequence[str], None] = '6ebf53cccd9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill NULL emails with unique placeholders, then enforce NOT NULL."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name = 'users'
                  AND column_name = 'email'
                  AND is_nullable = 'YES'
            ) THEN
                UPDATE core.users
                SET email = gen_random_uuid()::text || '@placeholder.local'
                WHERE email IS NULL;

                ALTER TABLE core.users
                ALTER COLUMN email SET NOT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Allow NULL emails again."""
    op.execute("ALTER TABLE core.users ALTER COLUMN email DROP NOT NULL")
