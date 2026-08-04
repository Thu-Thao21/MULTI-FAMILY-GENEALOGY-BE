import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.postgres import init_db, close_db
from app.routers import health, users, auth, members, networks

app = FastAPI(title="Multi-family Genealogy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # Initialize PostgreSQL DB and create tables / seed data if needed
    try:
        await init_db()
    except Exception as e:
        print(f"[WARN] Postgres init_db error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    await close_db()

app.include_router(health.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(networks.router, prefix="/api")

# To run: uvicorn app.main:app --reload --port 8001
