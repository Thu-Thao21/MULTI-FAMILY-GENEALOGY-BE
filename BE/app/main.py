import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from app.db.postgres import init_db, close_db
from app.routers import auth, family, genealogy, health


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local SQLite may create canonical tables. Neon is never mutated here.
    try:
        await init_db()
    except Exception as exc:
        print(f"[WARN] Postgres init_db error: {exc}")
    yield
    await close_db()


app = FastAPI(
    title="Multi-family Genealogy API",
    docs_url=None,
    lifespan=lifespan,
)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(family.router)
app.include_router(genealogy.router)

# To run: uvicorn app.main:app --reload --port 8001
