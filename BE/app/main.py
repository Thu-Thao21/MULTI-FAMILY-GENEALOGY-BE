import asyncio
import logging
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.controllers.auth_access.router import router as auth_router
from app.controllers.auth_access.user_admin_router import router as user_admin_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware
from app.db.postgres import check_db, close_db, init_db
from app.dependencies.auth import API_PREFIX
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
# Added last = outermost user middleware, so every request (including CORS
# preflight and error responses) gets a request_id.
app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)


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
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(user_admin_router, prefix=API_PREFIX)

# To run: uvicorn app.main:app --reload --port 8001
