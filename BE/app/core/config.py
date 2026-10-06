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
    # When true, unhandled-error logs include the traceback. Keep false outside local dev.
    DEBUG: bool = False
    # Firebase project whose ID tokens are accepted (token audience). No default on
    # purpose: when empty, POST /auth/session fails closed with 503.
    FIREBASE_PROJECT_ID: str = ""
    # Service account JSON path, only for the Admin API (password change, token
    # revocation check). The file content is never read or logged by app code.
    FIREBASE_SERVICE_ACCOUNT_PATH: str = ""
    # Application session lifetime and how fresh recent_id_token must be.
    SESSION_TTL_HOURS: int = 8
    RECENT_LOGIN_MAX_AGE_SECONDS: int = 300
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://localhost:8080"
    FRONTEND_URL: str = "http://localhost:5173"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # hide_input_in_errors: a validation error must never echo the offending value;
    # for DATABASE_URL that value is a connection string with the password.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
