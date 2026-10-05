import asyncio
import logging
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.postgres import check_db, close_db, init_db
from app.routers import health

logger = logging.getLogger("mfg")

app = FastAPI(title="Multi-family Genealogy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    try:
        await init_db()
        logger.info("Database connectivity check passed.")
    except Exception as exc:
        # Do not log exception text: SQLAlchemy often embeds DATABASE_URL.
        logger.error(
            "Database connectivity check failed at startup (%s). "
            "App will keep running; /api/health/ready will return 503.",
            type(exc).__name__,
        )


@app.on_event("shutdown")
async def shutdown_event():
    await close_db()


@app.get("/api/health/ready")
async def readiness():
    """Readiness: fails when SELECT 1 cannot reach the database."""
    try:
        await check_db()
        return {"status": "ready"}
    except Exception as exc:
        logger.error("Readiness check failed (%s).", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "database_unavailable"},
        )


app.include_router(health.router, prefix="/api")

# To run: uvicorn app.main:app --reload --port 8001
