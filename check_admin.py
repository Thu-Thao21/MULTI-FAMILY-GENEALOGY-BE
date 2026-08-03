import asyncio
from app.db.postgres import async_session_maker
from app.models.postgres import Admin, Account
from sqlalchemy import select

async def check():
    async with async_session_maker() as session:
        result = await session.execute(select(Admin))
        admins = result.scalars().all()
        print("=== ADMINS IN DB ===")
        for a in admins:
            print(f"ID: {a.id}, Username: {a.username}, Email: {a.email}, Role: {a.role}")
        
        result_acc = await session.execute(select(Account))
        accounts = result_acc.scalars().all()
        print("=== ACCOUNTS IN DB ===")
        for acc in accounts:
            print(f"ID: {acc.id}, Username: {acc.username}, Email: {acc.email}")

if __name__ == "__main__":
    asyncio.run(check())
