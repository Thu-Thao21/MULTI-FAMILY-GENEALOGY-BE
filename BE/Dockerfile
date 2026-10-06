# Backend image - FastAPI served by Uvicorn.
#
# Build context is this directory (BE/). Only app/, alembic/ and alembic.ini are copied:
# no scripts/ (the dev seed), tests/, docs/, .env or service-account files. Secrets are
# supplied at run time (DATABASE_URL, FIREBASE_PROJECT_ID, FIREBASE_SERVICE_ACCOUNT_PATH
# pointing at a mounted file); nothing is baked into the image.
#
# Python 3.13 matches the version the test suite runs on.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so this layer is cached until requirements.txt changes.
# All dependencies ship wheels (psycopg[binary]), so no compiler is needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Liveness only (/api/health does not touch the database). Readiness is /api/health/ready.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

# Behind a reverse proxy, login_history records the proxy's IP unless --proxy-headers and a
# trusted proxy list are configured (docs/known_issues.md KI-11).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
