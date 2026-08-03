import asyncio
from app.db.postgres import async_session_maker
from app.models.postgres import Admin, Account, AccountRole
from app.core.security import hash_password
from sqlalchemy import select

async def seed_admin():
    async with async_session_maker() as session:
        # Check if default admin exists in Admin table
        result = await session.execute(select(Admin).where(Admin.username == 'admin'))
        existing_admin = result.scalar_one_or_none()
        
        pwd_hash = hash_password('12060805')
        
        if not existing_admin:
            admin_obj = Admin(
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
            )
            session.add(admin_obj)
            print("Created Admin in 'admins' table!")
        else:
            existing_admin.password_hash = pwd_hash
            existing_admin.email = 'thuthaor120608@gmail.com'
            print("Updated Admin password hash and email in 'admins' table!")

        # Also seed into Account & AccountRole tables so both login modes work seamlessly!
        res_acc = await session.execute(select(Account).where(Account.email == 'thuthaor120608@gmail.com'))
        existing_acc = res_acc.scalar_one_or_none()
        if not existing_acc:
            acc_obj = Account(
                id='admin_default_001',
                firebase_uid='admin_default_001',
                username='admin',
                email='thuthaor120608@gmail.com',
                display_name='Quản Trị Viên Hệ Thống',
                password_hash=pwd_hash,
                email_verified=True,
                status='active'
            )
            session.add(acc_obj)
            await session.flush()
            role_obj = AccountRole(
                account_id='admin_default_001',
                role='admin',
                status='active'
            )
            session.add(role_obj)
            print("Created Admin in 'accounts' and 'account_roles' tables!")
        else:
            existing_acc.password_hash = pwd_hash
            print("Updated Account password hash in 'accounts' table!")

        await session.commit()
        print("=== SEED ADMIN COMPLETE! ===")

if __name__ == "__main__":
    asyncio.run(seed_admin())
