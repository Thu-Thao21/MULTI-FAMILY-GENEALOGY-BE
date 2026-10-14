import sys
import asyncio
import selectors
import uvicorn

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)

