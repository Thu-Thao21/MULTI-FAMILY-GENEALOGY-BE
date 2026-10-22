import asyncio
import sys
from app.db.postgres import async_session_maker
from sqlalchemy import text

sys.stdout.reconfigure(encoding='utf-8')

async def check_db():
    async with async_session_maker() as session:
        result = await session.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """))
        tables = [r[0] for r in result.fetchall()]
        print('Tables in PostgreSQL:', tables)
        
        for t in tables:
            try:
                cnt = await session.execute(text(f'SELECT count(*) FROM "{t}";'))
                print(f'Table {t}: {cnt.scalar()} rows')
            except Exception as e:
                print(f'Table {t}: error {e}')

if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_db())
