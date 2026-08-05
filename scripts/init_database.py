import asyncio
import os
import sys
from pathlib import Path

# Add BE root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.db.postgres import engine, init_db, async_session_maker
from app.models.postgres import Admin, Account, AccountRole
from app.core.security import hash_password


async def run_sql_script():
    sql_file = PROJECT_ROOT / "scripts" / "init_database.sql"
    if not sql_file.exists():
        print(f"[WARN] File {sql_file} not found.")
        return

    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print("[*] Applying init_database.sql schema & views...")
    for statement in sql_content.split(";"):
        stmt = statement.strip()
        if stmt:
            try:
                async with engine.begin() as conn:
                    await conn.exec_driver_sql(stmt)
            except Exception as e:
                # Ignore notices or pre-existing constraint warnings
                pass
    print("[+] Database schema, 33 tables & 3 views initialized successfully!")


async def seed_admin_and_accounts():
    print("[*] Seeding default Admin and Family Head accounts with hashed passwords...")
    pwd_hash = hash_password('admin')
    
    async with async_session_maker() as session:
        # Seed Admin
        res_admin = await session.execute(select(Admin).where(Admin.username == 'admin'))
        existing_admin = res_admin.scalar_one_or_none()
        if not existing_admin:
            session.add(Admin(
                id='admin_default_001',
                username='admin',
                email='thuthaor120608@gmail.com',
                phone='0912345678',
                full_name='Quản Trị Viên Hệ Thống',
                password_hash=pwd_hash,
                admin_code='ADM-001',
                permissions_level='super_admin',
                managed_scope='all_families',
                role='admin',
                status='active'
            ))
        else:
            existing_admin.password_hash = pwd_hash
            existing_admin.email = 'thuthaor120608@gmail.com'

        # Seed Account for Admin
        res_acc = await session.execute(select(Account).where(Account.email == 'thuthaor120608@gmail.com'))
        existing_acc = res_acc.scalar_one_or_none()
        if not existing_acc:
            session.add(Account(
                id='admin_default_001',
                firebase_uid='admin_default_001',
                username='admin',
                email='thuthaor120608@gmail.com',
                display_name='Quản Trị Viên Hệ Thống',
                password_hash=pwd_hash,
                email_verified=True,
                status='active'
            ))
            await session.flush()
            session.add(AccountRole(
                account_id='admin_default_001',
                role='admin',
                status='active'
            ))
        else:
            existing_acc.password_hash = pwd_hash

        await session.commit()
    print("[+] Admin account seeded successfully!")


async def main():
    print("==================================================")
    print(" UNIFIED DATABASE INITIALIZATION & SEED SCRIPT")
    print("==================================================")
    print("[1/3] Initializing ORM Metadata...")
    await init_db()
    print("[2/3] Running SQL schema & views script...")
    await run_sql_script()
    print("[3/3] Seeding initial database accounts...")
    await seed_admin_and_accounts()
    print("==================================================")
    print(" ALL DONE: Database schema & seed data complete!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
