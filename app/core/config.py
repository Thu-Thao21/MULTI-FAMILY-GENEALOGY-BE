import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    FIREBASE_PROJECT_ID: str = "multi-family-genealogy"
    FIREBASE_CREDENTIALS_PATH: str = ""

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""


    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if not settings.DATABASE_URL:
    settings.DATABASE_URL = "sqlite+aiosqlite:///./dev.db"

if os.getenv("DATABASE_URL"):
    settings.DATABASE_URL = os.getenv("DATABASE_URL")
