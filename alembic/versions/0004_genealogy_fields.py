"""add 14 genealogy fields for branches, persons, relationships (idempotent with IF NOT EXISTS)

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
    # 1. Bổ sung 5 cột cho bảng branches (IF NOT EXISTS để bảo đảm idempotent)
    op.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS code VARCHAR(50);")
    op.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS description TEXT;")
    op.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS branch_order INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now();")
    op.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now();")

    # 2. Bổ sung 4 cột cho bảng persons
    op.execute("ALTER TABLE persons ADD COLUMN IF NOT EXISTS generation_no INTEGER DEFAULT 1;")
    op.execute("ALTER TABLE persons ADD COLUMN IF NOT EXISTS avatar_storage_key TEXT;")
    op.execute("ALTER TABLE persons ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now();")
    op.execute("ALTER TABLE persons ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now();")

    # 3. Bổ sung 5 cột cho bảng relationships
    op.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS child_order INTEGER;")
    op.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS marriage_order INTEGER;")
    op.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false;")
    op.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT now();")
    op.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now();")


def downgrade() -> None:
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS updated_at;")
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS created_at;")
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS verified;")
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS marriage_order;")
    op.execute("ALTER TABLE relationships DROP COLUMN IF EXISTS child_order;")

    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS updated_at;")
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS created_at;")
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS avatar_storage_key;")
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS generation_no;")

    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS updated_at;")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS created_at;")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS branch_order;")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS description;")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS code;")
