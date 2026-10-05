from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise ValueError(
            "DATABASE_URL is required. Set it in the environment or BE/.env "
            "(postgresql+psycopg://user:password@host/dbname?sslmode=require)."
        )
    if value.startswith("sqlite"):
        raise ValueError(
            "SQLite is not supported. DATABASE_URL must use postgresql+psycopg:// "
            "against the assigned Neon/PostgreSQL branch."
        )
    if value.startswith("postgresql+psycopg://"):
        return value
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    raise ValueError(
        "DATABASE_URL must start with postgresql+psycopg:// "
        "(postgresql:// and postgres:// are accepted and normalized)."
    )


class Settings(BaseSettings):
    DATABASE_URL: str
    FIREBASE_PROJECT_ID: str = "multi-family-genealogy"
    FIREBASE_CREDENTIALS_PATH: str = ""
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://localhost:8080"
    FRONTEND_URL: str = "http://localhost:5173"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, value: object) -> str:
        if value is None:
            raise ValueError(
                "DATABASE_URL is required. Set it in the environment or BE/.env "
                "(postgresql+psycopg://user:password@host/dbname?sslmode=require)."
            )
        return _normalize_database_url(str(value))

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]


settings = Settings()
