import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from app.db.postgres import engine, Base
import app.models.postgres

async def fix_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        alter_statements = [
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS password_hash TEXT;",
            "ALTER TABLE families ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);",
            "ALTER TABLE families ADD COLUMN IF NOT EXISTS branches JSON DEFAULT '[]';",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS account_id VARCHAR(36);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS username VARCHAR(150);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS email VARCHAR(255);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS password_hash TEXT;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'member';",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS sub_branch VARCHAR(120);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS lunar_death_date VARCHAR(80);",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS burial_place TEXT;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS burial_coordinates JSON;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS gallery_photos JSON DEFAULT '[]';",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS career_history JSON DEFAULT '[]';",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS contact JSON;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS privacy_settings JSON;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS contribution JSON;",
            "ALTER TABLE members ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE;",
        ]
        for stmt in alter_statements:
            try:
                await conn.execute(text(stmt))
                print(f"Executed: {stmt}")
            except Exception as e:
                print(f"Skipped {stmt}: {e}")

if __name__ == "__main__":
    asyncio.run(fix_schema())
