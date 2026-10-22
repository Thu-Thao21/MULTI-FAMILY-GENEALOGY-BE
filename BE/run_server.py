import os
import sys
import asyncio
import selectors
import uvicorn
from dotenv import load_dotenv

# Ensure .env from BE folder is loaded
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.main import app

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8001, loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        selector_loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(selector_loop)
        selector_loop.run_until_complete(main())
    else:
        asyncio.run(main())
