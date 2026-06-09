"""add hash chain columns to audit_log

Revision ID: 002_audit_hash_chain
Revises: 001_initial_tables
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_audit_hash_chain"
down_revision = "001_initial_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("entry_hash", sa.String(64), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "entry_hash")
