import asyncio, sys, traceback

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.postgres import check_db

async def test():
    try:
        await check_db()
        print('check_db SUCCEEDED!')
    except Exception as e:
        print('check_db FAILED:')
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test())
