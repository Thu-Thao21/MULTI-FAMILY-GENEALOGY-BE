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
from app.controllers.family_management.public_router import router as public_router
from app.core.config import settings
from app.core.errors import UnhandledErrorMiddleware, register_exception_handlers
from app.core.rate_limit import build_rate_limiters
from app.core.request_id import RequestIdMiddleware
from app.core.startup_checks import ConfigurationError, validate_runtime_config
from app.db.postgres import check_db, close_db, init_db
from app.dependencies.auth import API_PREFIX
from app.routers import health

logger = logging.getLogger("mfg")

def create_app() -> FastAPI:
    """Build the application. The module-level `app` below is the one uvicorn serves;
    tests call create_app() to get a fresh instance they can extend."""
    application = FastAPI(title="Multi-family Genealogy API")

    # Middleware order: the LAST one added is the OUTERMOST. From outside in:
    #   RequestIdMiddleware -> CORSMiddleware -> UnhandledErrorMiddleware -> handlers/routes
    # UnhandledErrorMiddleware must sit inside CORS so a 500 envelope still gets the
    # Access-Control-* headers; RequestIdMiddleware outermost so every response, preflight
    # and error included, carries a request_id.
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Without this the browser hides these headers from frontend JavaScript.
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)
    # In-memory, per process (docs/known_issues.md KI-17). Tests replace it to use a fake clock.
    application.state.rate_limiters = build_rate_limiters(settings)
    return application


app = create_app()


@app.on_event("startup")
async def startup_event():
    # Fail closed: a bad Firebase/CORS configuration stops the process with a clear
    # message (variable names only, never values). Runs before the DB check and only on
    # real startup, never on import.
    try:
        validate_runtime_config(settings)
    except ConfigurationError as exc:
        logger.critical("%s", exc)
        raise
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
app.include_router(public_router, prefix=API_PREFIX)

# To run: uvicorn app.main:app --reload --port 8001
