"""workflow_enhancements

Revision ID: 0002_workflow_enhancements
Revises: 55f9e299872e
Create Date: 2026-11-26 00:25:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002_workflow_enhancements"
down_revision: Union[str, None] = "55f9e299872e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_assignments",
        sa.Column("forward_reason", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("task_assignments", "forward_reason")
