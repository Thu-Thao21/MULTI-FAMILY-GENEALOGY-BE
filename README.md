Backend (FastAPI + MongoDB)

Quickstart:
1. Copy .env.example to .env and update MONGODB_URI and MONGODB_DB.
2. Create a virtualenv and install dependencies:
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
3. Run the server:
   uvicorn app.main:app --reload --port 8000

Endpoints:
- GET /api/health
- GET /api/users
- POST /api/users

This backend uses Motor for async MongoDB access. Replace the placeholder in-memory user store with MongoDB CRUD as needed.
