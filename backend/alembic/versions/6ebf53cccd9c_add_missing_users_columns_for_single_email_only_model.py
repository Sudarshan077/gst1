"""add missing users columns for single email-only model

Revision ID: 6ebf53cccd9c
Revises: 86f8e79e7a13
Create Date: 2026-10-07 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ebf53cccd9c'
down_revision: Union[str, Sequence[str], None] = '86f8e79e7a13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add mobile_verified_at, totp_secret, totp_enabled_at, notification_preferences."""
    op.execute(
        "ALTER TABLE core.users ADD COLUMN IF NOT EXISTS "
        "mobile_verified_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE core.users ADD COLUMN IF NOT EXISTS "
        "totp_secret VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE core.users ADD COLUMN IF NOT EXISTS "
        "totp_enabled_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE core.users ADD COLUMN IF NOT EXISTS "
        "notification_preferences JSONB"
    )


def downgrade() -> None:
    """Reverse the column additions."""
    op.drop_column('users', 'notification_preferences', schema='core')
    op.drop_column('users', 'totp_enabled_at', schema='core')
    op.drop_column('users', 'totp_secret', schema='core')
    op.drop_column('users', 'mobile_verified_at', schema='core')
