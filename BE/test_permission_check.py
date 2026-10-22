import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.db.postgres import async_session_maker
from app.models.postgres import User
from app.services.auth_access.access_service import AccessService
from sqlalchemy import select

async def main():
    async with async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == 'dev-sa@example.test'))).scalar_one()
        access = AccessService(db)
        clan_id = '3d906850-41c9-4cf9-bae0-71910b10f504'
        print("Checking roles for user:", user.email, "id:", user.id)
        roles = await access.repo.get_active_roles(user.id, clan_id)
        print("Active roles returned:", roles)
        try:
            await access.require_family_permission(user, clan_id, 'relationship.view')
            print("Permission GRANTED!")
        except Exception as e:
            print("Permission DENIED:", getattr(e, 'status_code', None), getattr(e, 'detail', str(e)))

if __name__ == '__main__':
    asyncio.run(main())
