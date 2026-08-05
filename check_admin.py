import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.db.postgres import async_session_maker
from app.models.postgres import Admin, Account, AccountRole, Member
from app.core.security import verify_password, hash_password

async def check():
    async with async_session_maker() as session:
        res_a = await session.execute(select(Admin))
        admins = res_a.scalars().all()
        print("=== ADMINS TABLE ===")
        for a in admins:
            print(f"ID: {a.id}, Username: {a.username}, Email: {a.email}, Role: {a.role}")
            print(f"  Password Hash: {a.password_hash[:30]}...")
            print(f"  Verify 'admin': {verify_password('admin', a.password_hash)}")
            print(f"  Verify '12060805': {verify_password('12060805', a.password_hash)}")

        res_acc = await session.execute(select(Account))
        accs = res_acc.scalars().all()
        print("\n=== ACCOUNTS TABLE ===")
        for ac in accs:
            print(f"ID: {ac.id}, Username: {ac.username}, Email: {ac.email}")
            print(f"  Password Hash: {ac.password_hash[:30] if ac.password_hash else 'None'}")
            if ac.password_hash:
                print(f"  Verify 'admin': {verify_password('admin', ac.password_hash)}")
                print(f"  Verify '12060805': {verify_password('12060805', ac.password_hash)}")

if __name__ == "__main__":
    asyncio.run(check())
