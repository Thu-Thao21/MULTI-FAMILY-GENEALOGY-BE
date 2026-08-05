import sys
import asyncio
import selectors
import uvicorn

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8000, loop="asyncio")
        server = uvicorn.Server(config)
        asyncio.run(server.serve(), loop_factory=loop_factory)
    else:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000)

