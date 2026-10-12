"""add 14 genealogy fields for branches, persons, relationships

Revision ID: 0004_genealogy_fields
Revises: 0003_provisioning_idempotency
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_genealogy_fields"
down_revision: Union[str, Sequence[str], None] = "0003_provisioning_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Bổ sung 5 cột cho bảng branches
    op.add_column("branches", sa.Column("code", sa.String(50), nullable=True))
    op.add_column("branches", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("branch_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("branches", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("branches", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

    # 2. Bổ sung 4 cột cho bảng persons
    op.add_column("persons", sa.Column("generation_no", sa.Integer(), server_default="1", nullable=True))
    op.add_column("persons", sa.Column("avatar_storage_key", sa.Text(), nullable=True))
    op.add_column("persons", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("persons", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

    # 3. Bổ sung 5 cột cho bảng relationships
    op.add_column("relationships", sa.Column("child_order", sa.Integer(), nullable=True))
    op.add_column("relationships", sa.Column("marriage_order", sa.Integer(), nullable=True))
    op.add_column("relationships", sa.Column("verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("relationships", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("relationships", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_column("relationships", "updated_at")
    op.drop_column("relationships", "created_at")
    op.drop_column("relationships", "verified")
    op.drop_column("relationships", "marriage_order")
    op.drop_column("relationships", "child_order")

    op.drop_column("persons", "updated_at")
    op.drop_column("persons", "created_at")
    op.drop_column("persons", "avatar_storage_key")
    op.drop_column("persons", "generation_no")

    op.drop_column("branches", "updated_at")
    op.drop_column("branches", "created_at")
    op.drop_column("branches", "branch_order")
    op.drop_column("branches", "description")
    op.drop_column("branches", "code")
