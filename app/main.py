from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.mongodb import connect_mongo, close_mongo, get_database
from app.api.routes import health, users, auth

app = FastAPI(title="Multi-family Genealogy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # connect to MongoDB
    connect_mongo(settings.MONGODB_URI)
    # ensure database access possible (lazy)
    db = get_database(settings.MONGODB_DB)
    # You can create indexes here or verify connection

@app.on_event("shutdown")
async def shutdown_event():
    close_mongo()

app.include_router(health.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(auth.router, prefix="/api")

# To run: uvicorn app.main:app --reload --port 8000
