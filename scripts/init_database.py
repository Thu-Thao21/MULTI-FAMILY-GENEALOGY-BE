import asyncio
import os
import sys
from pathlib import Path

# Add BE root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.postgres import engine, init_db


async def run_sql_script():
    sql_file = PROJECT_ROOT / "scripts" / "init_database.sql"
    if not sql_file.exists():
        return

    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print("[*] Applying init_database.sql schema & views...")
    async with engine.begin() as conn:
        for statement in sql_content.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    await conn.exec_driver_sql(stmt)
                except Exception as e:
                    print(f"[WARN] Statement execution notice: {e}")
    print("[+] Database schema & views initialized successfully!")


async def main():
    print("[*] Initializing PostgreSQL database tables...")
    await init_db()
    await run_sql_script()
    print("[+] ALL DONE: Database is clean and ready.")


if __name__ == "__main__":
    asyncio.run(main())
