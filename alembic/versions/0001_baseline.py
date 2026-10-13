"""baseline: the schema of the dev database already exists

This revision is EMPTY on purpose. It records "the tables are already there" and nothing else.

Which schema is "already there"? The one in the dev database that the ORM maps and that
docs/schema_user_access.txt and docs/schema_family.txt describe (checked by
scripts/check_orm_vs_db.py). database/initial_schema.sql is an OLDER export: it lacks tables
such as user_sessions and clan_memberships, columns such as users.username and the index
uq_active_user_role_scope, so it is NOT enough to build that schema.

A brand-new, empty database therefore does NOT get its tables from `alembic upgrade`, and it
cannot be built from initial_schema.sql alone. See docs/migrations.md.

Running it only creates the alembic_version table and stores this revision id in it.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-06
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Nothing to do: the schema already exists."""


def downgrade() -> None:
    """Nothing to undo."""
