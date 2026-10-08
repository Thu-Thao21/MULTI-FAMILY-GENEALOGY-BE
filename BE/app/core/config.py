from pydantic import field_validator, model_validator
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

    # Rate limiting of the public endpoints (Mốc E, step E3): in memory, per process, per IP
    # (docs/known_issues.md KI-17). Defaults: registration 5 per hour, track 20 per 10 minutes.
    # Raise RATE_LIMIT_REGISTRATION_MAX for a demo on a shared network.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REGISTRATION_MAX: int = 5
    RATE_LIMIT_REGISTRATION_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_TRACK_MAX: int = 20
    RATE_LIMIT_TRACK_WINDOW_SECONDS: int = 600
    RATE_LIMIT_MAX_KEYS: int = 10_000
    # X-Forwarded-For is ignored unless this is true (the caller can write that header).
    # TRUSTED_PROXY_COUNT is how many proxies sit in front of the app; the address is the
    # Nth entry counted from the RIGHT of the header.
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_COUNT: int = 1

    # Owner provisioning (Mốc E6). Every Firebase Admin call is bounded by FIREBASE_CALL_TIMEOUT_SECONDS;
    # a RUNNING job holds its lease for PROVISIONING_LEASE_SECONDS. A run makes at most THREE
    # Firebase calls (get_user, create_user or set_password, delete_user), so the lease must outlast
    # three timeouts: 3 x timeout < lease (checked at start-up and by a test).
    FIREBASE_CALL_TIMEOUT_SECONDS: int = 15
    PROVISIONING_LEASE_SECONDS: int = 90
    # A job that has failed this many times can no longer be retried: it becomes FAILED.
    PROVISIONING_MAX_ATTEMPTS: int = 5
    # Temporary password of a new Owner: life, and whether it must hold a symbol (some Firebase
    # password policies require one; the default character set is letters and digits).
    OWNER_TEMP_PASSWORD_TTL_HOURS: int = 72
    OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL: bool = False

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

    @model_validator(mode="after")
    def validate_provisioning_timing(self) -> "Settings":
        # No value is echoed in these messages.
        for name in (
            "FIREBASE_CALL_TIMEOUT_SECONDS", "PROVISIONING_LEASE_SECONDS",
            "PROVISIONING_MAX_ATTEMPTS", "OWNER_TEMP_PASSWORD_TTL_HOURS",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if 3 * self.FIREBASE_CALL_TIMEOUT_SECONDS >= self.PROVISIONING_LEASE_SECONDS:
            raise ValueError(
                "PROVISIONING_LEASE_SECONDS must be longer than three Firebase calls: "
                "3 x FIREBASE_CALL_TIMEOUT_SECONDS < PROVISIONING_LEASE_SECONDS."
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]


settings = Settings()
