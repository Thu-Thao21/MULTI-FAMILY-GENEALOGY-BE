Backend (FastAPI + PostgreSQL)

Quickstart:
1. Copy .env.example to .env and update DATABASE_URL.
2. Create a virtualenv and install dependencies:
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
3. Run seed sample data (optional):
   python scripts/seed_sample_data.py
4. Run the server:
   uvicorn app.main:app --reload --port 8000

Endpoints:
- GET /api/health
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/forgot-password/request-otp
- POST /api/auth/forgot-password/reset

This backend uses SQLAlchemy (AsyncSession) + psycopg for PostgreSQL access.
